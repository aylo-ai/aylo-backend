# MinIO media storage migration — security and cost hardening

**Date:** 2026-08-04
**Scope:** Move all user media (knowledge-base documents, message audio, campaign
images) from AWS S3 to self-hosted MinIO, and fix the storage-layer defects the
migration would otherwise have carried forward.

A deep audit of the storage subsystem ran first (`.claude/agents/deep-auditor.md`,
added by this change). Its findings drove the work below. Findings it raised that
fall outside the storage layer are listed under **Open items** rather than fixed
silently.

---

## 1. Needs a human decision today

| Id | Severity | What |
|---|---|---|
| **C1** | **Critical** | A live Google service-account private key is committed to the repository. |

`apps/shared/addons/repli-ai-cred.json` contains `"type": "service_account"`,
`project_id: repli-ai`, `client_email: repli-ai@repli-ai.iam.gserviceaccount.com`
and a full 1704-byte `-----BEGIN PRIVATE KEY-----`. It is tracked, was added in
commit `6871111`, and `.gitignore` never covered it.

Anyone with repo read access — now or from any past clone, fork or CI artifact —
can authenticate as `repli-ai` and read every Google Doc and Sheet ever shared
with that service account, which is every customer's knowledge-base source.

**Code-side changes cannot fix this — they only stop it recurring.** Done here:

- The hardcoded path is replaced by `settings.GOOGLE_SERVICE_ACCOUNT_FILE`,
  defaulting to `secrets/google-service-account.json` outside the tree, mounted
  read-only into web and both Celery workers.
- `git rm --cached apps/shared/addons/repli-ai-cred.json` — **staged, not
  committed.** The file is still on disk and copied to `secrets/` so the current
  setup keeps working until the key is rotated.
- `.gitignore` covers `secrets/`, `*-cred.json`, `*service-account*.json`,
  `*.pem`, `*.key`. `.dockerignore` covers the same — without that, `COPY . /app`
  kept baking the private key into every image.
- Credential loading now fails soft instead of raising `FileNotFoundError`.

**Still required, by a human, in this order:**

1. **Revoke key `d720cc64…`** in the GCP console (IAM → Service Accounts → Keys).
   Everything below is secondary to this.
2. Issue a replacement, drop it at `secrets/google-service-account.json`.
3. Commit the staged deletion, and delete the file from disk once step 2 is done.
4. Purge it from history (`git filter-repo --path
   apps/shared/addons/repli-ai-cred.json --invert-paths`) and force-push.
   Revocation makes the leaked key useless; purging history is what stops it being
   handed to the next person who clones. Both are needed.

---

## 2. Fixed — storage architecture

MinIO speaks the S3 API, so no new dependency was needed: `django-storages
1.14.6` and `boto3` were already installed. The `minio` Python SDK was
deliberately not used — it does not plug into Django's `FileField`.

| Id | Sev | Location | Issue | Fix |
|---|---|---|---|---|
| H5 | High | `config/settings.py` | `STORAGES` used bare `S3Boto3Storage` with **no** `querystring_auth`, `querystring_expire`, `default_acl` or `file_overwrite` set — every access-control property was an inherited default, and setting `AWS_S3_CUSTOM_DOMAIN` would have made every media URL permanently unsigned and world-readable | Explicit `apps.shared.storages.MediaStorage`, all properties stated in code, `custom_domain` **refused** at construction with `ImproperlyConfigured` |
| M5 | Med | `config/settings.py:304,435` | `MEDIA_URL` defined twice; `MEDIA_ROOT` set while default storage was S3; `deployment/nginx` served `/media/` as an unauthenticated `alias /var/www/media/`; `compose.yml` bind-mounted that dir into four services | Single `MEDIA_URL`; nginx alias replaced by an authenticated MinIO proxy; all four bind mounts removed; `config/urls.py` no longer routes `MEDIA_ROOT` |
| M4 | Med | `apps/assistant/services/google.py:50` | Hand-rolled `upload_to_s3()` wrote a **second copy** of every payload to the bucket root with no DB row referencing it, under a key partly taken from the document title, via a bare `boto3.client` with no `endpoint_url` — it could never have addressed MinIO | Deleted. Both call sites now write once through the configured backend and return `file_upload.file.url`, which also fixes `file_url` having always been `None` |

### Why presigned URLs, and the one trap in it

The bucket is private; `MediaStorage.url()` returns a presigned URL that expires
(`MINIO_URL_EXPIRY`, default 1 h).

`S3Boto3Storage.url()` short-circuits on `custom_domain` and returns an
**unsigned** URL — it only signs when a CloudFront signer is present, which MinIO
has no equivalent of. Against a private bucket that is a 403 on every media link,
with no error at configuration time. Verified against the installed source
(`storages/backends/s3boto3.py`). `MediaStorage.__init__` now rejects the
combination outright, and a test asserts it.

A SigV4 signature covers the request **host and full path**. Django signs against
the public origin (`MINIO_PUBLIC_URL`) using a second boto3 client, while reads
and writes use the internal `http://minio:9000`. nginx therefore proxies
`/<bucket>/` through **without rewriting the path** — no trailing slash on
`proxy_pass`, no `rewrite`, `Host` forwarded unchanged. Any prefix stripping
breaks every media URL with a 403. Both properties are asserted in
`MinioNginxTests`.

---

## 3. Fixed — security

| Id | Sev | Location | Issue | Fix |
|---|---|---|---|---|
| H1 | High | `apps/assistant/serializers.py:246` | `MessageSerializer` had **no** size, extension or content-type check on `audio_file`. A 99 MB upload was buffered whole, `.read()` doubled it, then the request blocked on Whisper for up to the 600 s proxy timeout, billing per audio minute with no cap | `validate_audio()` in `validate()`, before any read or API call — 25 MB (the transcription API's own ceiling) and an extension allowlist |
| H2 | High | `config/settings.py:421` | `FILE_UPLOAD_MAX_MEMORY_SIZE = 104857600` meant Django **never** spilled to disk: every upload up to 100 MB lived in the worker's heap, so a handful of concurrent uploads OOM-killed the container | Lowered to 5 MB; larger files stream to a temp file. Added `FILE_UPLOAD_PERMISSIONS = 0o600` |
| M8 | Med | `apps/assistant/serializers.py`, `apps/dashboard/serializers.py` | Size-only validation — no extension or content-type allowlist anywhere. Any file type could be stored and served from the API origin | Shared `apps/shared/file_validation.py`. `.html` excluded from documents: the vector store indexes it, but stored HTML served from the API origin is a stored-XSS payload, and the same content is reachable as `.txt`/`.md` |
| M3 | Med | `apps/assistant/services/conversation.py:43` | `get_audio_from_url` fetched a webhook-supplied URL with a plain `http.get` — no destination validation, redirects followed. Blind SSRF into the Celery worker's network (Postgres, Redis, `169.254.169.254`), **made worse by MinIO**, which puts every customer's documents on an internal address the worker can reach | `http.fetch_external()`: rejects non-public addresses, re-validates **every** redirect hop, streams with a hard byte cap |
| M1 | Med | `apps/assistant/models.py:250` | `AssistantFileUpload.file` had no `max_length`, so the column was `varchar(100)` — but the key prefix alone is 53 chars. Long filenames were silently truncated onto **colliding** keys, and the longest raised `SuspiciousFileOperation` (500) | `max_length=255`, matching `Message.audio_file`. Migration `0051` |
| M2 | Med | `apps/assistant/models.py:20` | Keys were `assistant/<id>/files/<client filename>` with `file_overwrite=True`. Two uploads of `catalog.pdf` produced two rows sharing **one** object; deleting either deleted the file out from under the other | `build_media_key()` inserts a random segment per upload; `file_overwrite = False` |

### Key generation

`build_media_key(prefix, filename)` guarantees uniqueness and bounded length. A
content hash was considered for dedupe and rejected: it reintroduces exactly the
shared-object problem M2 was about. Filename sanitisation here is for
predictability, not security — Django basenames multipart filenames and
`S3Boto3Storage` rejects traversal independently. Path traversal was checked and
found **not** exploitable, before or after.

`comment_response_image_path` was also flat and misspelled
(`integrtion/<step id>/image/`), so no per-tenant bucket policy or lifecycle rule
could match it. Now `integration/flows/<flow>/steps/<step>/image/`. Existing rows
keep their stored keys.

---

## 4. Fixed — cost and correctness

| Id | Sev | Location | Issue | Fix |
|---|---|---|---|---|
| H3 | High | `apps/assistant/models.py`, `apps/integration/models.py` | **Nothing deleted stored objects.** A `delete()` override existed but Django only calls it for a single instance — `queryset.delete()` and FK cascades go straight to SQL. Deleting one assistant cascaded away every upload and message row while leaving every document and voice note in the bucket, unreferenced and unfindable. `grep -rn "cleanup\|orphan\|prune" apps/` returned nothing | `apps/shared/file_cleanup.py` registers `post_delete` handlers, which Django **does** emit for cascaded and bulk deletes. Registered in both `AppConfig.ready()`. Best-effort: a storage error is logged, never propagated |
| M7 | Med | `config/settings.py` | The suite issued **real** `PutObject` calls. It looked green only because this checkout had no credentials — with them it would have written test fixtures into production MinIO | `InMemoryStorage` under `test`, asserted by a test. This alone fixed 3 of the 4 pre-existing suite errors |
| — | Low | `apps/shared/addons/payloads.py`, `apps/assistant/tasks.py`, `config/celery.py` | Dead code calling `.url` in list comprehensions; a `print()`-containing task with no callers but a live Celery route | Deleted `create_assistant_payload`, `create_file_urls`, `save_uploaded_file` + its route, a 53-line commented block in `google.py`, and the unused imports each left behind (verified with `grep -rn` and `pyflakes`) |

---

## 5. Infrastructure

`compose.yml` gains `minio` and `minio-init`, following the hardening pattern
`test_deployment_compose.py` already enforces for Dozzle:

- **Loopback-only ports.** 9000 (S3 API) and 9001 (admin console) publish on
  `127.0.0.1` only; nginx stays the sole public listener. The console is off by
  default (`MINIO_BROWSER=off`) and nginx deliberately does not proxy it.
- **Least privilege.** The root credential never leaves the container.
  `deployment/minio/init.sh` provisions a separate user for Django with
  `deployment/minio/policy.json` scoped to the one bucket — no admin actions, no
  `s3:*`. A leaked app key cannot create users or read other buckets.
- **Anonymous access forced off on every boot**, even if an operator opened the
  bucket by hand from the console.
- `cap_drop: ALL`, pinned image tags, named `minio-data` volume, healthcheck.
- `init.sh` is idempotent — safe to re-run, never rotates a working credential.

Server-side encryption is **off by default and deliberately**: MinIO rejects
PutObject with an SSE header unless a KMS is configured, so enabling
`MINIO_SERVER_SIDE_ENCRYPTION` without `MINIO_KMS_SECRET_KEY` turns every upload
into a 500. Documented in `config/settings.py` and `.env.example`.

### Data migration

**No table is rewritten.** Every `FileField` stores a storage-relative key, not
an absolute URL, and there is no `AWS_LOCATION` in play — confirmed against the
model and migration definitions. Cutover is a key-preserving object copy plus an
endpoint change.

`manage.py migrate_media_to_minio` supports `--dry-run`, `--verify-only`,
`--include-orphans` and is resumable (skips keys already present, compares
sizes). The `--include-orphans` flag exists because the retired `upload_to_s3()`
wrote to the bucket root with no DB row — those objects are invisible to a
"copy what the DB references" walk.

---

## 6. Second pass — defects found in the implementation itself

The `deep-auditor` agent was run again against the finished diff, specifically to
find what the *migration* broke. It found four things that mattered. All are
fixed; each has a regression test.

| Id | Sev | What the first pass introduced | Fix |
|---|---|---|---|
| **V1** | **Critical** | `Step.message_image` was left at `max_length=100` while its new key grew to **146 characters** — measured, not estimated. `file_overwrite=False` routes to `Storage.get_available_name`, whose truncation loop consumed the whole filename and raised `SuspiciousFileOperation`. **Every** flow-step image upload would have 500'd, for every filename, and left an orphan `Flow` row because the loop is not atomic | `max_length=255` + migration `0044`; step id dropped from the key (two UUIDs plus prefix was 137 chars of pure overhead) |
| **V2** | **High** | `post_delete` deleted objects **inside** the request transaction. `ATOMIC_REQUESTS = True` (`config/settings.py:167`), so the signal always fires pre-commit — a rollback restored the rows while their files were already gone from MinIO. A live row pointing at nothing is strictly worse than the orphan being fixed. Reachable via `apps/dashboard/views.py` bulk user delete, where a deferred FK violation at COMMIT rolls back after the files are gone | Deletion deferred to `transaction.on_commit`, whose callbacks Django discards on rollback |
| **V3** | High | The Google key was still tracked by git *and* still baked into every image — `.gitignore` does nothing for an already-tracked file, and `.dockerignore` did not cover `*-cred.json`, so `COPY . /app` shipped the private key in the layer. Separately, the new `GOOGLE_SERVICE_ACCOUNT_FILE` default was not mounted and credential loading sat **outside** the `try`, turning a working import into an uncaught `FileNotFoundError` | `git rm --cached`; `.dockerignore` patterns; `./secrets:/app/secrets:ro` mounted into web + both workers; `_load_credentials()` fails soft |
| **V4** | High | Presigned URLs were logged in full at four sites. Pre-migration these were unsigned and leaked nothing; now each is a one-hour bearer capability for another tenant's document — written into logs that are exposed through Dozzle behind a single login | Log the object key or filename, never the query string |

Also fixed from the same pass:

- **Credential fallback (medium).** With `MINIO_ACCESS_KEY` blank, `access_key=None`
  reached boto3, which walked its own resolution chain and picked up the **legacy
  AWS keys still in the environment for the migration**. Every request then hit
  MinIO signed with an AWS key and 403'd as `InvalidAccessKeyId`. `MediaStorage`
  now refuses to construct without an explicit credential.
- **Validation bypass on update paths (medium).** `validate_audio` sat *below* the
  `if self.instance is not None: return attrs` short-circuit, so a `PATCH` to
  `MessageRetrieveView` (a `RetrieveUpdateDestroyAPIView` exposing `audio_file`)
  stored any size and any extension unchecked. `UpdateFileUploadSerializer` was
  still size-only although its `create()` stores rows.
- **Client-controlled `Content-Type` (medium).** django-storages sets an object's
  type from the client's multipart part header, so an allowlisted `.txt` could be
  stored as `text/html`. `ContentDisposition: attachment` now makes the stored
  type inert regardless.
- **Bucket-name/nginx coupling (medium).** `MEDIA_URL` derives from
  `MINIO_BUCKET_NAME` while nginx hardcodes `/aylo-media/`; changing the bucket
  silently 404'd all media. Now asserted by a test.
- **`UnboundLocalError` on `_` (pre-existing, in a method this change touched).**
  `transcribed_text, _, _ = media.transcribe_audio(...)` rebound gettext's `_` as
  a local for the whole method, so the `_("Request obyekti kerak")` above it
  raised `UnboundLocalError` instead of returning a clean validation error.
- Lows: `save()` rename guard in the migration command (it *does* rename on
  collision — the original comment was wrong); blank `MINIO_URL_EXPIRY` crashing
  at import; `TESTING` matching stray `test` argv tokens and missing pytest;
  `validate_image` wired into the one upload field that had no limit at all;
  `depends_on: minio-init: service_completed_successfully` so uploads cannot
  precede the bucket; a bounded, self-diagnosing wait in `init.sh`.

### Verified correct by the second pass

Worth recording, because these were the parts most likely to be subtly wrong:

- Presigned URLs through nginx: path-style + `Host $host` + `proxy_pass` with no
  URI. SigV4 covers neither scheme nor default port, and nginx forwards the raw
  `$request_uri`, so percent-encoded and non-ASCII filenames survive intact.
- The `url()` override matches the parent exactly. `filepath_to_uri` is only used
  in the `custom_domain` branch, which is now refused.
- `build_media_key` length budget is off by one in the **safe** direction.
- `post_delete` coverage is correct for instance, `queryset.delete()`, cascade and
  `all().delete()`.
- The SSRF guard resists `2130706433`, `0177.0.0.1`, `127.1`, `0`,
  `::ffff:127.0.0.1`, userinfo tricks, and multi-record DNS where only some
  answers are private. No fd leak. `Retry` cannot follow redirects.
- `FILE_UPLOAD_MAX_MEMORY_SIZE = 5 MB` breaks no read-then-save path;
  `TemporaryUploadedFile` is seekable and carries the same `.name`.
- No webhook regression from `validate_audio` — platform audio arrives as bytes
  through `create_message`, which never touches the serializer.

### Live verification performed

- `docker compose config -q` — valid.
- `docker compose up -d minio minio-init` — **`minio` reached `Healthy`**, so
  `mc ready local` works as a healthcheck in the pinned image.
- `init.sh`'s required-variable guard fired correctly on a missing
  `MINIO_BUCKET_NAME` rather than creating a wrongly-named bucket.
- With blank root credentials, MinIO **boots, reports healthy, and yet no
  credential authenticates** — including `minioadmin`. Confirmed directly against
  the running container (`/minio/health/live` → 200; `list_buckets` →
  `InvalidAccessKeyId` for `minioadmin`, `""` and `" "`). This is why the root
  vars now use compose's `:?` required form.

**Still not verified end to end:** a presigned URL fetched *through nginx*
returning 200. That needs the bootstrap to complete and nginx in front. It is the
highest-risk remaining step, and §8 says so.

## 7. Files changed

| File | Change |
|---|---|
| `.claude/agents/deep-auditor.md` | **New** — security + performance investigation agent |
| `apps/shared/storages.py` | **New** — `MediaStorage`, `build_media_key` |
| `apps/shared/file_cleanup.py` | **New** — `post_delete` object cleanup |
| `apps/shared/file_validation.py` | **New** — size + extension limits |
| `apps/shared/management/commands/migrate_media_to_minio.py` | **New** — S3 → MinIO copy |
| `deployment/minio/init.sh`, `policy.json` | **New** — bootstrap, scoped policy |
| `apps/shared/tests/test_storage.py` | **New** — 17 tests |
| `apps/shared/tests/test_http_ssrf.py` | **New** — 14 tests |
| `apps/shared/tests/test_file_validation.py` | **New** — 9 tests |
| `config/settings.py` | STORAGES block, upload limits, test storage, Google key path |
| `compose.yml` | minio + minio-init; removed 4 dead media bind mounts |
| `deployment/nginx/api.aylo.uz.conf` | `/aylo-media/` proxy replaces `/media/` alias |
| `apps/shared/http.py` | `assert_public_url`, `fetch_external` |
| `apps/assistant/models.py` | key generation, `max_length=255`, removed superseded `delete()` |
| `apps/integration/models.py` | key generation, fixed prefix typo |
| `apps/assistant/serializers.py` | audio + document validation |
| `apps/dashboard/serializers.py` | document validation |
| `apps/assistant/services/conversation.py` | SSRF-safe audio fetch |
| `apps/assistant/services/google.py` | deleted `upload_to_s3`, logging, settings-based key path |
| `apps/{assistant,integration}/apps.py` | cleanup signal registration |
| `apps/assistant/tasks.py`, `config/celery.py`, `apps/shared/addons/payloads.py` | dead code removal |
| `apps/assistant/tests.py` | mock Redis publish (suite must run offline) |
| `apps/shared/tests/test_deployment_compose.py` | +11 MinIO hardening / nginx tests |
| `config/urls.py`, `.gitignore`, `.env.example` | media route, secret patterns, new config |
| `apps/assistant/migrations/0051_…` | `max_length=255` |

## 8. Tests

57 new tests. Full suite:

```
$ .venv/bin/python manage.py test apps --keepdb
Using existing test database for alias 'default'...
Found 268 test(s).
System check identified no issues (0 silenced).
............................................................................
----------------------------------------------------------------------
Ran 268 tests in 2.131s

OK
```

Baseline at `HEAD` (738d9aa) for comparison — measured in a clean worktree, not
assumed: **210 tests, 4 errors**. Three were the tests hitting real object
storage (M7); the fourth needed a live Redis, now mocked.

---

## 9. Open items needing a human decision

**Blocking, do first:**

1. **C1** — revoke the Google key in GCP and purge it from git history. Nothing
   in this change can do that.
2. **Run the stack.** Docker is not accessible from this environment (the account
   is not in the `docker` group), so the compose services were **validated
   (`docker compose config -q`) but never started**. Before cutover, verify by
   hand: `mc ready local` works as a healthcheck in the pinned `minio/minio`
   image, `init.sh` completes, and a presigned URL fetched through nginx returns
   200 rather than 403 — that last one is the single highest-risk step.
3. **Generate credentials** (`openssl rand -hex 24` ×4) and add the new
   `MINIO_*` / `GOOGLE_SERVICE_ACCOUNT_FILE` keys to the production `.env`.
   `.env.example` documents each.
4. **Run the migration** — `--dry-run` first, then `--include-orphans` if the
   bucket-root files matter, then `--verify-only`.

**Found by the audit, outside this change's scope:**

| Id | Sev | What | Why not fixed here |
|---|---|---|---|
| H4 | High | Deleting or replacing a knowledge-base file via the dashboard (`apps/dashboard/views.py:1203`) or `AssistantFileUploadRetrieveView.update` (`apps/assistant/views.py:381`) leaves the document **live in the OpenAI vector store** with its `file_id` discarded — the agent keeps quoting deleted documents forever, with nothing left to clean up with. `DashboardAssistantFileUploadList.create` never indexes at all, so admin-uploaded files are invisible to the agent | Vector-store lifecycle, not storage. Needs a decision on whether the dashboard should index at all |
| M6 | Med | N+1 on every message list — `MessageListCreateView`, `MessageRetrieveView`, `ConversationMessagesListView` return bare querysets; `get_answered_by_name` dereferences per row. A 200-message conversation is 1 + 200 queries **plus 200 presign computations** | A query-layer change; wants `select_related` plus a decision on whether `audio_file` URLs belong in list responses at all (see below) |
| — | Med | Presigned URLs expire in 1 h but are returned inside cacheable JSON list responses. A frontend caching a message list longer than that shows broken audio | Needs a frontend contract decision: shorter cache, a refresh endpoint, or redirect-on-demand |
| — | Low | `InstagramCommentResponseFlowSerializer` declares `step = StepSerializer(...)` but the `related_name` is `steps` → guaranteed `AttributeError`/500. It currently **masks** a scoping gap: `InstagramCommentResponseFlowListCreateView.get_queryset` has no ownership check, so fixing the serializer alone converts a 500 into a **cross-tenant read** | Fix both together or neither |
| — | Low | `DashboardAssistantFileUploadDetail` PUT/PATCH is a guaranteed 500 — it uses a serializer whose `validate()` needs an `assistant` context the view never sets | Separate defect |
| — | Low | `knowledge_base._download` reads whole files into RAM with no cap, then `BytesIO` copies them — a 30 MB document is held twice in a worker | Wants streaming; `fetch_external` is the model to follow |
| — | Low | No content sniffing. The extension allowlist does not prove a `.pdf` is a PDF | Needs `libmagic`, a new dependency |
| — | Low | `assert_public_url` validates resolved addresses then connects, so a DNS rebind answering differently on the second lookup is not blocked. Documented in the code rather than left implicit | Closing it needs the connection pinned to the validated IP |
