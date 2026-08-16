# T-03 — Close the Dozzle exposure and stop logging secrets in nginx

**Date:** 2026-08-03 · **Branch:** `feat/t-03-dozzle-nginx-exposure` (uncommitted) ·
**Ticket:** `docs/reports/2026-08-03-wave2-backlog.md` §3 Round 1a, T-03
**Scope:** repo only. No nginx command was run, no host was touched.

---

## 1. Findings and fixes

### Critical — `/_logs/` was internet-reachable (criterion a, b)

`deployment/nginx/api.aylo.uz.conf:70-72` carried `allow` / `deny all` as comments while
`proxy_pass http://127.0.0.1:8080;` was live. Every container log for the `aylochat`
project was served to any address on the internet that reached
`https://api.aylo.uz/_logs/`, behind Dozzle's simple auth alone — and `users.yml` is
gitignored, so the strength of that one remaining layer is not verifiable from the repo.

**Fix:** the block now denies by default and allows only the host itself:

```
allow 127.0.0.1;
allow ::1;
deny  all;
```

**No allowlist source exists in this repository.** The only addresses present anywhere
are the host's own `143.198.112.70` and the two that were commented out — `203.0.113.4`
is RFC 5737 documentation space and `10.8.0.0/24` has no corresponding wireguard config
in the tree. Both were placeholders, not a deployment fact, so neither was reinstated.
The loopback-only list is the fail-closed reading: the viewer is reached over an SSH
tunnel (`ssh -N -L 8080:127.0.0.1:8080 root@api.aylo.uz`), which is documented in the
conf and in `deployment/dozzle/setup.sh`. A `TODO(H-1)` names what a human must supply
to allow browser access over TLS instead. **No IP was invented.**

The `location = /_logs` redirect deliberately has **no** access rules: `return` executes
in nginx's rewrite phase, which runs before the access phase, so an `allow`/`deny` there
would never be consulted. Putting one in would look like protection and be inert. The
redirect target is the block that 403s.

### High — the Telegram bot token was written to the access log (criterion c)

`access_log` at `:46` was inherited by `location /` at `:93`, and the legacy webhook
route embeds a customer's bot token as its last path segment
(`/api/v1/integration/telegram/webhook/<bot_token>/`). One inbound Telegram message wrote
one live credential to `/var/log/nginx/api.aylo.uz.access.log` in cleartext.

**Fix — suppression, not redaction.** A `map` on `$uri` drives conditional logging:

```
map $uri $aylo_request_is_loggable {
    ~^/api/v1/integration/telegram/webhook/  0;
    default                                  1;
}
...
access_log /var/log/nginx/api.aylo.uz.access.log combined if=$aylo_request_is_loggable;
```

Why suppression rather than a redacting `log_format`: a substitution that misses — an
encoded slash, a route that moves, a capture group that does not fire — writes the token
anyway, and there is no nginx in this environment to validate the regex against (running
one is out of scope for this ticket). A dropped line cannot half-fail. The cost is that
inbound-webhook volume no longer appears in this file; the application logs the same
events upstream. Keyed on `$uri` rather than `$request_uri` because `$uri` is normalized
and percent-decoded, so an encoded variant of the same path cannot slip past the regex.

This is belt-and-braces for the overlap window. Delete the map together with the legacy
route when T-02 lands; the test skips itself once that route stops resolving.

### Stated, not assumed — does the `logs` profile run in prod? (criterion d)

**No automated path starts it.** `deployment/deploy.sh:81-82` runs
`docker compose --profile "$NEW_COLOR"` (blue/green) and
`.github/workflows/dev-deploy.yml:58` runs `docker compose --profile green up --build -d`.
Neither ever requests `logs`, and `dozzle` / `docker-socket-proxy` are both
`profiles: [logs]` (`compose.yml:154,199`), so compose will not start them.

**UNVERIFIED from the repo:** whether a human ran `docker compose --profile logs up -d`
on the host. Both services carry `restart: unless-stopped`, so if that command was ever
run, the containers are still running today and survive reboots. `deployment/deploy.sh`
never runs `compose down`, so nothing would have stopped them either.
**Check on the host with `docker compose ps --profile logs` before assuming the exposure
was theoretical.** If the profile is up, the `users.yml` password should be treated as
having been exposed to the internet and rotated via `deployment/dozzle/setup.sh`.

### Correction to the ticket's premise (does not change the fix)

The ticket states the nginx access log "is what Dozzle then serves". It is not. nginx is
installed on the host, not as a compose service — there is no nginx container in
`compose.yml`, and the conf header documents `systemctl reload nginx`. Dozzle reads
container stdout via the socket proxy, filtered to
`label=com.docker.compose.project=aylochat`, so `/var/log/nginx/*.log` is outside its
view. The two findings compound through a different path, below.

---

## 2. Out-of-scope leak found — needs its own ticket

**`deployment/gunicorn_conf.py:141-142` writes the bot token to container stdout, which
Dozzle *does* serve.**

```
accesslog = "-"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'
```

`%(r)s` is the full request line, so every inbound Telegram webhook logs
`POST /api/v1/integration/telegram/webhook/<live-bot-token>/ HTTP/1.1` to the container
log — which is exactly what a Dozzle viewer reads, and what the nginx fix above does
*not* cover. This is the real compounding path between findings #2 and #3.

`deployment/gunicorn_conf.py` is outside the paths I own, so I did not touch it.
**Ticket request:** suppress or redact the webhook path in gunicorn's access log, either
by a `logger_class` that rewrites the path segment or by dropping gunicorn's access log
in favour of nginx's. Closed automatically by T-02 once the token leaves the URL, so it
may be simplest to fold into T-02's acceptance criteria rather than open a new ticket.

---

## 3. Files changed

| File | Change |
|---|---|
| `deployment/nginx/api.aylo.uz.conf` | `allow`/`deny all` uncommented and set loopback-only with a `TODO(H-1)`; `map $uri $aylo_request_is_loggable` added; `access_log` made conditional on it; comments corrected (rewrite-vs-access phase, `logs` profile is not deployed automatically) |
| `deployment/dozzle/setup.sh` | Header documents the SSH-tunnel access path; the "reachable from the internet" line is no longer true and was reworded |
| `apps/shared/tests/test_deployment_nginx.py` | **New.** Parses the real conf; 8 tests |

No dependency added. No application code touched.

---

## 4. Tests

`apps/shared/tests/test_deployment_nginx.py` parses `deployment/nginx/api.aylo.uz.conf`
itself (brace-matched location and map blocks, comments stripped) — not a fixture copy.

| Test | Asserts |
|---|---|
| `test_the_viewer_is_reachable_from_exactly_one_place` | exactly one location proxies to `127.0.0.1:8080` |
| `test_dozzle_upstream_is_never_proxied_from_an_unguarded_block` | any block reaching Dozzle contains `deny all` |
| `test_deny_all_is_the_last_access_rule` | no `allow` sits below the `deny` (nginx is first-match) |
| `test_allowlist_holds_no_documentation_placeholder_address` | no RFC 5737 / RFC 3849 address is shipped as if real |
| `test_the_deny_is_not_commented_out` | no `# deny` / `# allow` line — the exact regression |
| `test_the_webhook_path_maps_to_no_logging` | a `map $uri …` sends the webhook prefix to `0`, `default 1` |
| `test_the_access_log_is_conditional_on_that_map` | `access_log … if=$…` actually uses that variable |
| `test_the_mapped_prefix_is_a_real_route` | the suppressed prefix still resolves to `TelegramWebhookView`; skips once T-02 removes the route |

### Failing first, against the unfixed conf

```
FAILED (failures=6)
  test_every_block_reaching_dozzle_denies_by_default   location = /_logs reaches Dozzle without a deny
  test_dozzle_upstream_is_never_proxied_from_an_unguarded_block   location /_logs/ proxies to Dozzle openly
  test_deny_all_is_the_last_access_rule                location = /_logs has no deny all
  test_the_deny_is_not_commented_out                   '# allow 203.0.113.4;' matches '^#\s*(deny|allow)\b'
  test_the_webhook_path_maps_to_no_logging             no map keyed on the telegram webhook path
  test_the_access_log_is_conditional_on_that_map       no map keyed on the telegram webhook path
```

### Passing after the fix

```
$ .venv/bin/python manage.py test apps.shared --keepdb
Using existing test database for alias 'default'...
Found 117 test(s).
System check identified no issues (0 silenced).
.....................................................................................................................
----------------------------------------------------------------------
Ran 117 tests in 3.714s

OK
Preserving test database for alias 'default'...
```

### The tests fail when the protection is removed (DoD #2)

Re-commented the three access rules, deleted the map, and reverted `access_log` to its
old form; re-ran; restored:

```
FAIL: test_deny_all_is_the_last_access_rule
FAIL: test_dozzle_upstream_is_never_proxied_from_an_unguarded_block
FAIL: test_the_deny_is_not_commented_out
FAIL: test_the_access_log_is_conditional_on_that_map
FAIL: test_the_webhook_path_maps_to_no_logging
Ran 8 tests in 0.010s
FAILED (failures=5)
```

**Limit of this evidence, stated plainly:** these tests assert the *configuration*, not a
live 403. Nothing in this repo can issue an HTTP request to nginx, and running nginx was
out of scope for this ticket. `deny all` returning 403 to a non-allowlisted address is
standard `ngx_http_access_module` behaviour, but the end-to-end proof is the host-side
check in §5 and a human must perform it.

---

## 5. Self-review

| Item | Result |
|---|---|
| No secret, token or key value in code, logs, tests or fixtures | Pass. The test file contains no token; the placeholder path segment it resolves is the literal `placeholder-value`. No IP beyond loopback was added. |
| Errors fail closed, not open | Pass for access control: an empty/absent allowlist denies. Partially for logging: if the map regex ever stops matching (route moves), the line is logged again — which is why `test_the_mapped_prefix_is_a_real_route` exists to catch the route moving. |
| No new dependency | Pass. No package added; `if=` on `access_log` is stock `ngx_http_log_module` (since 0.7.0) and `map` is `ngx_http_map_module`, both in the standard build. |
| Test fails if the protection is removed | Pass — demonstrated above. |
| Dead code adjacent to the change removed | The commented-out placeholder `allow` lines were the dead code; they are gone. |
| Repo conventions | Tests run via `.venv/bin/python manage.py test apps.shared --keepdb`; `apps.` import prefix; `SimpleTestCase`, no DB, no network; follows `test_deployment_compose.py`'s pattern of asserting deployment config in the Django suite. |

---

## 6. Rollback note

**To revert:** `git checkout -- deployment/nginx/api.aylo.uz.conf deployment/dozzle/setup.sh`
and delete `apps/shared/tests/test_deployment_nginx.py`. Config only — no migration, no
data touched, nothing to reconcile.

**Order on the host, if the change is deployed and must come back out:**

1. `cp deployment/nginx/api.aylo.uz.conf /etc/nginx/sites-available/api.aylo.uz`
2. `nginx -t` — **must pass before step 3.** This is the human step; it was not run here.
3. `systemctl reload nginx`

Reverting re-opens `/_logs/` to the internet and resumes writing bot tokens to the access
log, so a revert should be paired with `docker compose --profile logs stop dozzle`.

**Left behind by a revert:** every access-log line already written. Rotation is
compressed, not deleted, by logrotate, so `zgrep` the archive —
`/var/log/nginx/api.aylo.uz.access.log*` — for the webhook prefix. **Any bot token found
there is compromised and must be regenerated in BotFather**; this fix stops new writes
and does nothing about lines already on disk. Same for container logs via the gunicorn
issue in §2.

---

## 7. Open items for a human

| # | Item |
|---|---|
| H-1 | Supply office / VPN egress addresses for the `/_logs/` allowlist, or confirm SSH-tunnel-only is the intended access model and delete the TODO. |
| H-2 | Run `docker compose ps` on the host and state whether Dozzle has been running. If yes: the `users.yml` password was exposed to the internet — rotate it, and treat any bot token in the access log as leaked. |
| H-3 | `deployment/gunicorn_conf.py` logs the token to container stdout (§2). Fold into T-02 or open a ticket — it is outside T-03's owned paths. |
| H-4 | The nginx **error** log still records the full request line on upstream errors (502/504), so a token can land there on failure. Not suppressed: silencing it would blind us to upstream faults. Closed by T-02. |
