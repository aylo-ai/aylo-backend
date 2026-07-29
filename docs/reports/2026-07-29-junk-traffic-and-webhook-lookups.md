# 2026-07-29 — Blocking junk crawler traffic, plus two bugs it surfaced

## Context

The dev host's access log was full of requests like:

```
172.18.0.1 - - [29/Jul/2026:20:21:17 +0500] "GET /roller-mcnutt-funeral-home-obituaries-....html HTTP/1.0" 400 143 "-" "...Chrome/48..."
172.18.0.1 - - [29/Jul/2026:20:22:21 +0500] "GET /robots.txt HTTP/1.0" 400 143 "-" "...Googlebot/2.1..."
172.18.0.1 - - [29/Jul/2026:20:22:37 +0500] "GET /app/uploads/2022/06/Rudy_the_Radiated_Tortoise....jpg HTTP/1.0" 400 143 "https://staging.tnaqua.org" "..."
```

Every one is `400 143` — a 143-byte Django `DisallowedHost` body. `ALLOWED_HOSTS`
(`config/settings.py:25`) was doing its job; none of these reached a view. The URLs and
the `staging.tnaqua.org` referer are SEO-spam crawl targets, i.e. bots crawling either the
raw IP or parked domains whose DNS points at `143.198.112.70`. This is ambient noise on
any public IP, not traffic aimed at Repli.

The problem was not the volume — it was that the requests reached gunicorn at all, and
that they revealed the app port was publicly bound.

## Issues found and fixed

### Infrastructure

| # | Severity | Issue | Fix |
|---|---|---|---|
| 1 | High | `compose.yml` published `8001:8000` / `8002:8000`, which binds `0.0.0.0`. gunicorn was reachable directly from the internet, bypassing nginx — no TLS, no `client_max_body_size 100M`, no host access log. Docker's published-port DNAT rules are evaluated before ufw's INPUT chain, so the host firewall did **not** cover this. | Bound both to `127.0.0.1` |
| 2 | Medium | nginx had no `default_server`. With only `server_name api.aylo.uz` defined, every request whose Host matched nothing fell through to that block and was proxied to gunicorn, which burned a worker to produce a 400. | Added `deployment/nginx/00-catchall.conf` returning `444` on :80 and :443 |

Note: the 2026-07-27 deployment report claimed "app binds `127.0.0.1:8002`" and
"8001/8002 stay loopback-only". That was not true of `compose.yml` as written — fix #1
makes it true for the first time.

### Application

Found by running the test suite as part of this change, not by the traffic itself.

| # | Severity | Issue | Fix |
|---|---|---|---|
| 3 | High | `views.py:319-320` filtered `Integration.objects.filter(sender_id=…)` and `filter(account_id=…)`. Neither field exists on `Integration` (the columns are `instagram_user_id` / `instagram_account_id`), so the standard Instagram DM webhook branch raised `FieldError` → 500. | Use the existing `Integration.instagram_by_id()` helper, matching the already-correct `views.py:310-311` |
| 4 | High | `views.py:254` had the same `filter(account_id=…)` bug in the Instagram **comment** branch. | Same helper |
| 5 | Medium | `set_telegram_webhook()` `print()`ed the webhook URL, whose path embeds the bot token (`serializers.py:78`); `get_webhook_info()` `print()`ed a response body containing the same URL. A live credential was going to stdout and therefore into the container logs. Violates CLAUDE.md §3 on both counts (`print()`, logging secrets). | Replaced with `logger` calls that record status only |

## Files changed

| File | Change |
|---|---|
| `compose.yml` | Bind `web-blue` / `web-green` published ports to `127.0.0.1` |
| `deployment/nginx/00-catchall.conf` | **New** — `default_server` catch-all returning `444` on :80 and :443 |
| `deployment/nginx/api.aylo.uz.conf` | Cross-reference the catch-all in the install steps |
| `apps/integration/views.py` | Three broken field lookups → `Integration.instagram_by_id()` |
| `apps/shared/addons/telegram.py` | Module logger; stop printing the bot token |
| `apps/shared/tests/test_telegram_webhook_logging.py` | **New** — 4 regression tests |

## Verification

**nginx catch-all** — syntax-checked and run for real on nginx 1.24.0 with the ports
remapped to 18080/18443 and a throwaway cert:

| Probe | Result |
|---|---|
| `GET /roller-mcnutt-...html` with `Host: staging.tnaqua.org` | curl exit 52 (empty reply), `http_code=000` |
| `GET /robots.txt`, no matching host | curl exit 52 |
| HTTPS with unknown SNI | curl exit 52 |
| access log bytes written | 0 |

Exit 52 with no status code is the connection being closed with no response — `444`
behaving as intended. Nothing is proxied and nothing is logged.

**Test suite:**

```
$ .venv/bin/python manage.py test apps --keepdb
Found 188 test(s).
System check identified no issues (0 silenced).
............................................................................................................................................................................................
----------------------------------------------------------------------
Ran 188 tests in 8.557s

OK
```

Issues #3 and #4 were each covered by tests already in `apps/integration/tests.py` that
had been failing with `FieldError`; they pass now. Issue #5 has four new tests.

## Deployment steps (not yet applied to the host)

1. `docker compose --profile green up -d --force-recreate web-green` — the port binding
   only changes on container recreation.
2. Install the catch-all:
   ```
   cp deployment/nginx/00-catchall.conf /etc/nginx/sites-available/00-catchall
   ln -sfn /etc/nginx/sites-available/00-catchall /etc/nginx/sites-enabled/
   rm -f /etc/nginx/sites-enabled/default
   nginx -t && systemctl reload nginx
   ```
3. Confirm from outside: `curl -sv http://143.198.112.70:8002/health/` should now fail to
   connect, and `curl -s -H 'Host: whatever' http://143.198.112.70/` should return nothing.

## Open items for a human

| Item | Note |
|---|---|
| `apps/shared/addons/telegram.py` still has ~20 other `print()` calls | Lines 92–120, 178–207 etc. None leak credentials, but all violate CLAUDE.md §3. Left alone to keep this change scoped; worth a dedicated pass. |
| Running tests with bare app labels is misleading | `manage.py test integration` reports a spurious `integration.tasks` import error, and `manage.py test shared integration` produces 2 phantom failures whose identity shifts between runs — both are dual-import-path artifacts (CLAUDE.md §5). Use the `apps.` prefix: `manage.py test apps.integration`. Worth stating in CLAUDE.md §5. |
| Was the Instagram DM webhook broken in production? | Issues #3/#4 are a hard 500 on those branches. The observed log line `Integration not found for Instagram account 17841408103243288` is `views.py:324`, which sits *after* the broken lookup — so the deployed host may be running code older than commits `0c8c606`/`3376b53`. Worth confirming what revision the host actually has. |
| `ssl_reject_handshake` | The :443 catch-all reuses the certbot cert because it is portable to any nginx. On ≥1.19.4 (the host has 1.24.0) it can be replaced with `ssl_reject_handshake on;` and no cert at all. |
