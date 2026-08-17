# MinIO uploads reaching nothing — diagnosis and fix

**Date:** 2026-08-17
**Reported as:** "I added MinIO successfully but for some reason files did not upload to it."

The MinIO integration itself was never the problem. The code on `origin/dev` is
correct and every upload path already goes through the Django storage backend.
Three *separate* faults, none of them in that code, meant no byte ever reached
the bucket.

---

## 1. Root causes

| # | Severity | Fault | Evidence |
|---|---|---|---|
| R1 | **Blocker** | The MinIO code was not in the working tree. Local `dev` was 14 commits behind `origin/dev` (0 local-only commits). `STORAGES["default"]` resolved to a bare `S3Storage` with `bucket_name=None`, `endpoint_url=None`, `access_key=None` | A real `storage.save()` raised `ValueError: Required parameter name not set` — the upload failed before any network call |
| R2 | **Blocker** | MinIO was never bootstrapped. `deployment/minio/init.sh` had never run against the live server, so the bucket and the scoped app user did not exist | Root credential listed **zero** buckets; app credential returned `InvalidAccessKeyId`; `HeadBucket` returned 403 |
| R3 | **High** | `deployment/nginx/api.aylo.uz.conf` had **no `location /aylo-media/` block**. In production every presigned URL would fall through to `location /`, reach gunicorn, and 404 | The file still had the dead `location /media/` disk alias instead |

R1 and R2 are independent: fixing either alone still leaves uploads broken.

The 2026-08-04 migration report predicted exactly this. Its "Open items" said the
stack was *"validated (`docker compose config -q`) but never started"* and listed
"Run the stack" and "Run the migration" as blocking. Neither was done.

## 2. Two committed merge conflicts

Found while running the suite — unrelated to MinIO but blocking all of it:

| File | Effect |
|---|---|
| `apps/shared/tests/test_deployment_compose.py` | Conflict markers at L50/56/67 → `SyntaxError` on import. **This hid `MinioNginxTests`, the class that already tested for R3.** The nginx gap was detectable all along |
| `apps/payment/tests.py` | Conflict markers at L328/520/665 → `SyntaxError` on import |

Both resolved keeping the substantive content of both sides:

- `test_deployment_compose.py`: both sides asserted the same thing; kept
  `self.project` (already set in `setUp`) with the clearer docstring.
- `apps/payment/tests.py`: the two sides add five **distinct, non-overlapping**
  test classes (`CardTokenBindingTests`, `CardWriteProtectionTests`,
  `PaymentThrottleTests` / `PublicCatalogueTests`,
  `PaymeVerificationThrottleTests`) and two differently-named throttle helpers.
  No name collides, so both sides were kept in full — no coverage dropped.

## 3. What was done

1. **Preserved your uncommitted work** on `wip/pre-minio-merge` (41 files).
   `secrets/google-service-account.json` was deliberately **excluded** — it is
   untracked and *not* gitignored on the old branch. `origin/dev` adds the
   ignore rule.
2. **Fast-forwarded `dev`** to `origin/dev` (`4984394` → `7a28729`).
3. **Bootstrapped MinIO** by running the project's own `deployment/minio/init.sh`
   against the live server — created bucket `aylo-media`, policy
   `aylo-media-rw`, the scoped app user, and set anonymous access to `none`.
4. **Fixed the nginx media route** to the shape `MinioNginxTests` already
   specified, including `limit_except GET HEAD { deny all; }`.
5. **Added `manage.py check_minio`** — a preflight that proves an upload really
   lands, because no unit test can (settings swap in `InMemoryStorage` under
   `manage.py test`).

## 4. Files changed

| File | Change |
|---|---|
| `deployment/nginx/api.aylo.uz.conf` | +`location /aylo-media/` proxying to MinIO unrewritten, read-only from the edge; −dead `location /media/` disk alias |
| `apps/shared/management/commands/check_minio.py` | **new** — end-to-end media preflight with actionable failure messages |
| `apps/shared/tests/test_deployment_compose.py` | resolved conflict markers |
| `apps/payment/tests.py` | resolved conflict markers, both sides kept |

## 5. Tests

`MinioNginxTests` + `MinioHardeningTests` — the config tests that were
unreachable behind the conflict marker, now passing:

```
$ .venv/bin/python manage.py test \
    apps.shared.tests.test_deployment_compose.MinioNginxTests \
    apps.shared.tests.test_deployment_compose.MinioHardeningTests
Ran 14 tests in 0.073s

OK
```

Live end-to-end against the running MinIO (`manage.py check_minio`):

```
backend  apps.shared.storages.MediaStorage
endpoint http://127.0.0.1:9000
bucket   aylo-media
[ok  ] upload  _healthcheck/3830409ca1a54f03b64260f12fc10aef.txt
[ok  ] read back  22 bytes
[ok  ] url is signed
[ok  ] presigned URL fetches
[ok  ] unsigned URL is refused
[ok  ] delete

all checks passed — media uploads reach MinIO
```

A wider ad-hoc probe (15 assertions) additionally confirmed: bytes are stored
byte-identical; the bucket refuses unsigned reads with 403; keys are uniquified,
sanitised and fit `varchar(255)`; two uploads of one filename get distinct keys;
and both `assistant_file_path` and `assistant_audio_path` route through
`build_media_key`.

Failure paths were verified too, not just the happy path — a wrong
`MINIO_ACCESS_KEY` and a wrong `MINIO_BUCKET_NAME` each produce a message naming
`init.sh` as the fix, instead of a bare `403`.

### The production signing path, verified

The check above runs with `MINIO_PUBLIC_URL` empty, so it proves the *local*
path only. Production is different and riskier: `MediaStorage.url()` signs for
`https://api.aylo.uz`, and MinIO only sees that host because nginx forwards it.
That was reproduced directly — the real `MediaStorage` configured with a public
origin, then its URL replayed against the live MinIO exactly as the new nginx
block would forward it (same path, same query, `Host: api.aylo.uz`, connection
to `127.0.0.1:9000`):

```
signed for : https://api.aylo.uz/aylo-media/_proxysim/report.pdf
[PASS] URL is signed against the PUBLIC host, not the internal one -- api.aylo.uz
[PASS] MinIO accepts the proxied presigned GET -- HTTP 200
[PASS] bytes survive the round trip -- 23 bytes
[PASS] a path-rewriting proxy_pass DOES break it -- HTTP 400
[PASS] dropping `Host $host` DOES break it -- HTTP 403
[PASS] HEAD on a GET-signed URL is refused by SigV4, not by nginx -- HTTP 403
[PASS] PUT is refused -- HTTP 403
```

The two failure rows matter as much as the passes: they confirm the config
comments are load-bearing rather than superstition. Writing
`proxy_pass http://127.0.0.1:9000/;` (trailing slash) or omitting
`proxy_set_header Host $host;` each breaks every media link, and both were
demonstrated rather than asserted.

**Behavioural note for the frontend.** A presigned URL is bound by SigV4 to one
HTTP method. A URL signed for `get_object` returns **403 for HEAD** — so a
HEAD preflight before the GET will fail even though the GET works. This is the
signature enforcing itself; `limit_except GET HEAD` in nginx is the outer guard
and lets HEAD through. Confirmed by signing the same object for `head_object`,
which then returns 200 for HEAD.

### Still unverified

nginx itself was never executed — it is not installed here, and the deployed
config could not be reloaded. The simulation reproduces what the block *specifies*
(path preserved, query preserved, `Host` preserved); it cannot catch a typo that
makes nginx refuse to start. Run `nginx -t` on the host before reloading.

### Not run

**The DB-backed suite could not be run.** Postgres is not up: `.env` points at
`127.0.0.1:55432` and nothing listens there (a system Postgres on `5432` rejects
the `repli` user). Docker is unreachable from this account — not in the `docker`
group, no passwordless sudo. The config-only `SimpleTestCase` suites were run
against an in-memory SQLite shim; `apps/shared/tests/test_storage.py` and the
rest need the real database.

**Please run this yourself and confirm it is green:**

```bash
docker compose up -d postgres redis minio minio-init
.venv/bin/python manage.py test apps --keepdb
```

## 6. Open items needing a human decision

| # | Item |
|---|---|
| O1 | **Pre-existing, unrelated, failing:** 5 nginx tests. `DozzleAllowlistTests` ×3 — the `/_logs/` `allow`/`deny all` rules are still commented out, so the log viewer is public behind Dozzle's own login alone. `TelegramWebhookAccessLogTests` ×2 — no `map` suppressing the webhook path, so **bot tokens are being written to the nginx access log**. Both predate this work and are security issues in their own right |
| O2 | `secrets/google-service-account.json` is on disk and was untracked-but-not-ignored on the old branch. The 2026-08-04 report's item **C1** — revoke that key in GCP and purge it from git history — is still open |
| O3 | The legacy media migration has **not** been run. If the old AWS bucket holds files users still reference: `manage.py migrate_media_to_minio --dry-run`, then without the flag, then `--verify-only` |
| O4 | `.env` sets `MINIO_ENDPOINT_URL=http://127.0.0.1:9000`, correct for host-run Django. Compose passes the same `.env` to the containers, where `127.0.0.1` is the container itself — it must be `http://minio:9000` there. Also `MINIO_PUBLIC_URL` is empty; production needs `https://api.aylo.uz` or presigned URLs get signed for the internal host |
| O5 | `.env` has `DB_PORT=55432` but nothing listens there. Unrelated to MinIO, but it blocks the test suite |
| O6 | The nginx block hardcodes `/aylo-media/`. Renaming `MINIO_BUCKET_NAME` breaks every media URL; `test_the_location_matches_the_configured_bucket` guards it |
