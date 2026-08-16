# Wave 1 — Devil's advocate (2026-08-03)

Read-only review. No code changed. Arguments strongest first.

---

## 1. Token encryption at rest is theater, and shipping it will break the Telegram webhook

The headline priority is the weakest item on the board.

**It cannot work as designed.** `apps/integration/views/telegram.py:41` authenticates the
webhook by *equality lookup on the ciphertext column*:
`Integration.objects.filter(api_token=bot_token)`. `apps/assistant/services/conversation.py:97`
does the same on `Conversation.token`. AES-256-GCM with a per-record nonce is randomized —
these lookups return nothing. You need a deterministic blind index (HMAC-SHA256 of the token,
indexed) before any nonce touches the column. Nobody scoped that. Ship encryption without it
and every Telegram bot on the platform dies at once.

**Even done correctly it protects nothing here.** The same secret is in plaintext in at least
three other places:

| Plaintext copy | Evidence |
|---|---|
| `conversation.token` — a second column holding the *same* bot token | `apps/assistant/models.py:128`, written at `conversation.py:108` |
| nginx access log, forever — the bot token is a **URL path segment** | webhook registered at `apps/integration/serializers.py:83,92`; `access_log` on for `location /` at `deployment/nginx/api.aylo.uz.conf:46,93` |
| `.env` / `/opt/aylo/.secrets/.env`, next to the key | `compose.yml:8,36,62,72,96` — every service loads it |

An attacker with DB read gets the key from the same host. An attacker with host read gets
`/var/log/nginx/api.aylo.uz.access.log` and does not need the DB at all. Encryption at rest
stops exactly one thing: a stolen `pg_dump` or a stolen disk volume. That is a real but narrow
threat, and it is *third* behind arguments 2 and 3.

**Changes my mind:** a written threat model naming stolen-backup as the modelled adversary,
plus a KMS/`sops` design where the key is *not* in `.env`, plus a blind-index spec. Absent
those three, it is compliance cosplay.

---

## 2. Meta's data-deletion callback deletes nothing. This is the real existential risk.

`apps/integration/views/instagram_oauth.py:244-266`: `InstagramDataDeletionView` validates the
signed request, logs, and returns a confirmation code. **It deletes zero rows.** Conversations,
messages and lead PII survive untouched.

Worse, the status URL it hands Meta is `https://api.repli.uz/integration/instagram/data-deletion-status/`
(line 263) — a **dead domain** (product is api.aylo.uz) at a path that **is not in
`apps/integration/urls.py`** (only `instagram/data-deletion/` is routed, line 19). A Meta
reviewer following that URL gets DNS failure or 404.

This is a failed app review, which is a dead product. `instagram_business_manage_messages` is
revocable at Meta's discretion; the whole architecture assumes it. Telegram de-risks the
*channel*, not the *revenue* — the Instagram OAuth flow, comment automation, flows, media sync
and broadcast are all Meta-only code paths (`apps/integration/views/`, 7 of 12 modules).

**Changes my mind:** a screenshot of a passed app review with these endpoints live.

---

## 3. We forward third-party DMs to OpenAI with `store: True` and have no retention policy

`apps/shared/ai_service/agent.py:234` sets `"store": True` explicitly, and chains turns with
`previous_response_id` (line 237). Every DM from someone who never signed our ToS is persisted
on OpenAI's servers. `CELERY_BEAT_SCHEDULE` (`config/settings.py:464-481`) has four jobs —
billing, Billz sync, statistics, follow-ups. **No purge job.** Message rows
(`apps/assistant/models.py:157`) are immortal; grep for `retention|purge|anonymi` across `apps/`
returns only blog copy.

Under GDPR this is unlawful on three counts: no lawful basis for the DM sender, no erasure path,
and a US sub-processor with no documented DPA/ZDR. Uzbek law No. ZRU-547 requires personal data
of Uzbek citizens to be processed on servers *in Uzbekistan* — sending Uzbek DMs to OpenAI is
squarely against it, and the customer base is Uzbek.

**Changes my mind:** an OpenAI ZDR agreement, a signed DPA, and a legal opinion on ZRU-547.

---

## 4. No global rate limit exists. 132 of 144 endpoints are unthrottled.

`config/settings.py:95-97` sets `DEFAULT_THROTTLE_CLASSES` to `ScopedRateThrottle` **only** —
it is inert on any view without `throttle_scope`. Twelve views set one
(`apps/user/views.py`, `apps/payment/views.py`, `apps/landing/views.py:23`). `"anon": "10/minute"`
(line 99) is used by a single view, `apps/dashboard/views/auth.py:16`. Both webhooks, every list
endpoint, the whole dashboard: unlimited. This is cheaper to fix than crypto and stops a more
likely outage.

---

## 5. Dozzle is internet-exposed with its IP allowlist commented out

`deployment/nginx/api.aylo.uz.conf:70-72` — `allow`/`deny all` are commented. `https://api.aylo.uz/_logs/`
is reachable from anywhere, guarded only by Dozzle's simple auth from a `users.yml` that is not
in git (`git ls-files deployment/dozzle/` → only `setup.sh`), so its strength is unverifiable.
The container hardening above it (`compose.yml:129-200`) is excellent work defending a door left
open. **UNVERIFIED:** whether the `logs` profile is running in prod.

---

## 6. "100% coverage" — concrete costs

144 endpoints, 15 test files. Full coverage is roughly 400+ tests nobody will read. Costs:
CI minutes; every WS-1/WS-2 refactor invalidating tests written against the old structure;
false confidence — 100% line coverage would not have caught argument 2, because the deletion
handler's happy path *passes*. Cover authz denials and money paths. Stop.

---

## 7. Kill list

1. **`InstagramDataDeletionView` (`instagram_oauth.py:244`)** — delete and rewrite; a handler
   that lies to a regulator is worse than none.
2. **`Conversation.token` (`assistant/models.py:128`)** — a duplicated bot-token column that
   also blocks encryption. Migrate to `conversation.integration_id` and drop it.
3. **The bot-token-in-URL webhook scheme (`serializers.py:83,92`)** — replace with an opaque
   per-integration UUID path + Telegram's `X-Telegram-Bot-Api-Secret-Token` header. Until then,
   encrypting `api_token` is pointless.
4. **WS-5/WS-6/WS-7 perf work** — scale is UNVERIFIED. No user count, no p95, no table sizes.
   Indexing on hot tables without measurement is how you take an outage during a migration.
   Measure first, or cut the wave.
