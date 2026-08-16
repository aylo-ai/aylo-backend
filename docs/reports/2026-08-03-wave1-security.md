# Wave 1 — Application Security Audit (read-only pass)

**Date:** 2026-08-03 · **Branch:** `dev` @ `4984394` · **Scope:** whole backend repo, migrations, CI.
No code was modified.

## Disagreement with the brief

> "Instagram/Telegram long-lived access tokens (claimed to be stored encrypted in the DB — verify this claim)"

**The claim is false.** There is no encryption anywhere in this codebase. `grep -rn "encrypt|Fernet|AESGCM|cryptography|decrypt" --include=*.py apps/ core/ config/` returns exactly one hit — a marketing sentence in `apps/blog/management/commands/seed_blog_posts.py:4315` claiming "encrypted storage". `apps/integration/models.py:31-32` stores both credentials as bare `models.TextField`. There is no key env var in `.env.example`, no `cryptography` in `requirements.txt`, no ciphertext version prefix, no key_id column. Every question in brief item 1 about algorithm, nonce, AEAD and rotation is therefore moot: **there is nothing to evaluate.** Section 1 below answers them as "N/A — plaintext".

Second correction: `2026-07-31` and `2026-08-01` prior fixes I was asked to verify **are genuinely in the code** — `owned_assistants()` scoping in `apps/assistant/views.py`, `IntegrationOwnedQuerysetMixin` (`apps/integration/views/mixins.py`), `STAFF` removed from `DASHBOARD_ROLES` (`apps/shared/permissions.py:22-27`), `api_token` write-only (`apps/integration/serializers.py:55,135`), forced `user_role=STAFF` (`apps/user/serializers.py:428`). I found no IDOR in the tenant-facing apps. The remaining risk is credential handling and data lifecycle, not authorization.

Scale is UNVERIFIED; no finding below depends on load.

## Findings

| # | Sev | Title | File:line | Impact | Fix |
|---|---|---|---|---|---|
| 1 | **P0** | Channel tokens stored in plaintext | `apps/integration/models.py:31-32` | Any DB read — backup, replica, SQL injection, stolen dump — yields full control of every customer's Telegram bot and Instagram DMs | Envelope-encrypt with AES-256-GCM + versioned prefix (§Migration) |
| 2 | **P0** | Telegram bot token is a URL path segment, and nginx logs it | `apps/integration/urls.py:14`, `deployment/nginx/api.aylo.uz.conf:46` | Every inbound Telegram message writes a customer bot token in cleartext to `api.aylo.uz.access.log` | Move to `X-Telegram-Bot-Api-Secret-Token`; opaque webhook id in path |
| 3 | **P0** | Dozzle log viewer IP allowlist is commented out | `deployment/nginx/api.aylo.uz.conf:64-72` | `/_logs/` exposes all container logs (and, with #2, tokens) to the internet behind Dozzle's own auth alone | Uncomment `deny all` + allowlist |
| 4 | **P1** | Meta data-deletion callback deletes nothing | `apps/integration/views/instagram_oauth.py:245-265` | Meta-mandated deletion request is logged and acked; no DM content is ever removed | Implement real deletion; fix the stale `api.repli.uz` URL |
| 5 | **P1** | Deauthorize leaves all DM content behind | `apps/integration/views/instagram_oauth.py:204-243` | Disconnecting an account deletes the `Integration` only; `Conversation`/`Message` hang off `Assistant` and survive forever | Cascade deletion by platform + account id |
| 6 | **P1** | No IG token refresh; return value discarded | `apps/integration/gateways/instagram.py:38,43-50`; `config/settings.py:464-481` | `instagram_refresh_token()` has one caller which throws away its result, and no beat entry refreshes; every IG integration dies silently at ~60 days | Add a daily beat task; persist the refreshed token |
| 7 | **P1** | Instagram OAuth callback has no `state` | `apps/integration/views/instagram_oauth.py:46-78` | Account-linking CSRF; `SessionAuthentication` is enabled and DRF does not CSRF-check GET | Mirror the Google flow (`apps/user/views.py:292-293`) |
| 8 | **P1** | Tokens and DM bodies ride in Celery payloads | `apps/integration/views/telegram.py:98,105,116`; `.../instagram_webhook.py:139,196` | Plaintext bot tokens + customer DM text sit in Redis queue entries and result backend | Pass `integration_id`; load the token in the worker |
| 9 | **P1** | No retention policy for third-party DM content | `apps/assistant/models.py:157-186` | `Message.message_content` is plaintext and unbounded; no cleanup task exists anywhere | Add a retention beat task; document the window |
| 10 | **P2** | Access tokens in outbound query strings | `apps/integration/gateways/instagram.py:32,46`; `.../instagram_oauth.py:153` | Tokens (and `client_secret` at :32) land in upstream/proxy logs | Move to POST body or header |
| 11 | **P2** | Ephemeral ngrok origin trusted with credentials | `config/settings.py:229,258` | `CORS_ALLOW_CREDENTIALS=True` + a reclaimable `*.ngrok-free.app` host in both CORS and CSRF trust lists | Delete both entries |
| 12 | **P2** | Admin-account enumeration oracle | `apps/dashboard/views/auth.py:29,31` | Distinct unauthenticated responses for "not an admin" vs "no such user" enumerate every platform admin | One generic message |
| 13 | **P2** | Dashboard OTP verify is unthrottled | `apps/dashboard/views/auth.py:38-41` | The send view has `AnonRateThrottle`; the verify view has none | Add an `otp_verify` scope |
| 14 | **P2** | `str.format` on operator-supplied template | `apps/shared/ai_service/prompts.py:53`; `apps/dashboard/views/assistants.py:184-187` | `IsDashboardUser` includes `support_agent`, who can store `{system_prompt.__class__.__mro__…}` and traverse attributes | `string.Template` or an explicit placeholder allowlist |
| 15 | **P2** | 7-day access tokens, no revocation | `config/settings.py:262` | Logout blacklists the refresh token only; a stolen access token stays valid a week | 15–60 min access lifetime |
| 16 | **P2** | HSTS 1 hour, asserts `preload` | `config/settings.py:209-210` | `preload` requires ≥1 year; `SECURE_SSL_REDIRECT` is unset (nginx redirects, so defence in depth only) | `SECURE_HSTS_SECONDS = 31536000` |
| 17 | **P3** | `hub.verify_token` compared with `==` | `apps/integration/views/instagram_webhook.py:66` | Non-constant-time compare of a low-value secret | `hmac.compare_digest` |
| 18 | **P3** | Unbounded `_download` follows redirects | `apps/shared/ai_service/media.py:93-100` | No size cap and no host allowlist; gated behind HMAC-verified webhooks, so not reachable today | Cap size, block private ranges |
| 19 | **P3** | Dead code | `apps/user/serializers.py:312-347` | `AddUserSerializer` (accepts an arbitrary `user_role`) and `DeleteCompanyUsersSerializer` have no callers — a wiring mistake becomes escalation | Delete (CLAUDE.md §4) |

**Verified sound** (no action): IG webhook HMAC uses `request.body` with `hmac.compare_digest` and fails closed when the secret is unset (`instagram_webhook.py:41-59`); `parse_signed_request` likewise (`instagram_oauth.py:161-201`); no raw SQL outside a hardcoded `SELECT 1` health probe (`apps/dashboard/views/system.py:25`); no `eval`/`exec`/`pickle`/`subprocess`; tool handlers bind `conversation` from the caller, not from model output (`apps/shared/ai_service/tools.py:99-110`), so DM prompt injection cannot cross tenants; `.env` never entered git history (only `.env.example` was ever added); CI takes secrets from GitHub Secrets and copies the env file from `/opt/aylo/.secrets` outside the tree.

## Proof

**#1 — plaintext tokens.** `api_token = models.TextField(null=True, blank=True)` at `apps/integration/models.py:31`. `SELECT api_token FROM integration;` returns live Telegram bot tokens and IG long-lived tokens. A bot token alone is full control of the customer's bot (read history, impersonate, `setWebhook` to attacker infrastructure). Second copy: `Conversation.token` (`apps/assistant/models.py:129`) stores the same bot token once per conversation and indexes it (`:148`).

**#2 — token in the access log.** Route: `path("telegram/webhook/<str:bot_token>/", ...)` (`apps/integration/urls.py:14`), registered by `set_telegram_webhook(api_token, f"{base_url}/api/v1/integration/telegram/webhook/{api_token}/")` (`apps/integration/serializers.py:83,92`). nginx: `access_log /var/log/nginx/api.aylo.uz.access.log;` at `deployment/nginx/api.aylo.uz.conf:46`, inherited by `location /` (`:93`). One customer DM → one log line containing that customer's bot token. Compounds with #3.

**#3 — Dozzle.** `deployment/nginx/api.aylo.uz.conf:64-72`: `allow` and `deny all` are all commented out; `proxy_pass http://127.0.0.1:8080;` is live. `https://api.aylo.uz/_logs/` is internet-reachable.

**#4 — deletion no-op.** `InstagramDataDeletionView.post` (`instagram_oauth.py:245-265`) verifies the signed request, calls `logger.info(...)`, and returns `{"url": "https://api.repli.uz/...", "confirmation_code": user_id}`. No ORM call. The URL is on the retired domain.

**#5 — orphaned DM content.** `InstagramDeauthorizeView` (`:204-243`) deletes `InstagramCommentResponse`, `InstagramMedia` and the `Integration`. `Conversation` FKs `Assistant` (`apps/assistant/models.py:114`), not `Integration`, so no cascade reaches it. Every third-party DM body survives.

**#6 — token expiry.** `get_long_lived_access_token` calls `self.instagram_refresh_token(access_token)` at `instagram.py:38` and discards the return; the method returns the *new* token (`:43-50`). `CELERY_BEAT_SCHEDULE` (`config/settings.py:464-481`) has four entries, none for tokens. At ~60 days every Graph call 401s; `send_message` fails soft, so DMs are dropped silently with no owner notification.

**#7 — no OAuth state.** `InstagramCallbackView.get` reads `code`, `assistant_id`, `is_automation_only` — no `state`. With `is_automation_only=true` no `assistant_id` is required and `user` may be `None` (`:47`), so an unauthenticated request creates an ownerless `Integration` holding a live IG token (`:145-150`). Contrast `GoogleLoginView` (`apps/user/views.py:292-293`), which does issue and consume a state token.

**#8 — Celery payloads.** `process_voice_task.delay(chat_id, voice_file_id, bot_token)` (`views/telegram.py:105`), `process_collected_messages.apply_async((chat_id, bot_token, None, chat_username, username, None), ...)` (`:116`), `handle_postback_event_task.delay(messaging[0], integration.api_token)` (`instagram_webhook.py:139`). Broker is Redis (`config/settings.py:393-397`), JSON-serialized, and `REDIS_PASSWORD` defaults to `""`.

**Related, informational:** `agent.py:234` sets `"store": True` on every Responses API call, so all customer DM text is retained by OpenAI. Whether the published privacy policy discloses this is UNVERIFIED — the policy lives in the `PrivacyPolicy` table, not in the repo. `IsDashboardUser` includes `support_agent`, and `/dashboard/conversations/` is deliberately cross-tenant: every support agent can read every third party's DMs. That is a design decision, not a bug, but it needs an audit trail.

## Migration plan — token encryption, zero downtime, no row invalidation

The hard constraint is #2: `TelegramWebhookView` looks the integration up **by token value** (`views/telegram.py:41`), so a naive randomized-nonce scheme breaks webhook routing. Sequence:

1. **Key material.** Add `FIELD_ENCRYPTION_KEYS` (comma-separated, base64, newest first) as a mandatory env var when `DEBUG=False`, mirroring the `SECRET_KEY` guard at `config/settings.py:16-22`. Distinct keys per environment; store in `/opt/aylo/.secrets/backend.env`, which is already outside the tree. Add `cryptography` to `requirements.txt` — it is already a transitive dependency of `google-auth`, so this adds no new supply-chain surface.
2. **Format.** `v1:<key_id>:<b64 nonce>:<b64 ct||tag>` — AES-256-GCM, 96-bit nonce from `os.urandom` per write, integration UUID as AAD. Decryption fails closed and is logged without the ciphertext. The `v1:` prefix makes rotation a re-encrypt loop, not an outage.
3. **Decouple the lookup first (deploy 1, no data change).** Add `Integration.webhook_secret` (indexed, `secrets.token_urlsafe(32)`) and register Telegram's own `secret_token`, so routing stops depending on the token's plaintext value. Accept both the legacy path and the new one during the overlap; re-run `setWebhook` per integration in a backfill task.
4. **Dual-read (deploy 2).** Add `api_token_enc` / `refresh_token_enc`. A descriptor reads `_enc` when populated and falls back to the plaintext column; writes always go to `_enc`. No backfill yet — nothing breaks if the deploy is rolled back.
5. **Backfill (deploy 3).** Chunked management command re-saves each row; idempotent and resumable.
6. **Cut over (deploy 4).** Flip reads to `_enc`-only, then `RemoveField` the plaintext columns in a separate migration once a full backup cycle has passed. Do the same for `Conversation.token` — or better, replace it with an FK to `Integration` and drop the duplicate secret entirely.
7. **Then** revoke: every Telegram token that has been in an nginx access log must be regenerated via BotFather, and IG integrations re-authorized. Encryption at rest does not undo #2 — rotation does.

Order matters: 3 before 4, and 7 only after 6, or webhook routing breaks mid-flight.
