# Webhook & callback hardening — 2026-08-04

Covers two passes over the unauthenticated attack surface:

1. **Pass A (earlier, interrupted session):** `apps/integration/views.py`,
   `gateways/telegram.py`, `tasks/telegram.py`, `serializers.py`,
   `apps/dashboard/views.py`. Code was written, **no tests**.
2. **Pass B (this session):** the missing test suite for Pass A, plus the first
   audit of `apps/payment/views.py`, `apps/landing/views.py` and
   `apps/blog/views.py`, which had never been reviewed.

Everything below runs offline — OpenAI, Telegram, Instagram, Payme and Redis are
mocked or faked.

---

## 1. Findings by severity

### Critical

| # | Endpoint | Issue | Fix | Pass |
|---|---|---|---|---|
| C1 | `POST /api/v1/landing/lead-bot/webhook/` | Fully unauthenticated Telegram webhook. Any caller could POST a forged `/verify` update naming **their own** `chat.id` and subscribe that group to every future landing lead — full name, phone number, Telegram handle. The only barrier was a password whose default value, `repli2024`, was **committed to this repository**. | Verify `X-Telegram-Bot-Api-Secret-Token` against `settings.LEAD_BOT_WEBHOOK_SECRET` with `compare_digest`; fail closed when unset. Password default removed (unset now refuses every verification) and compared with `compare_digest`. `throttle_scope = "lead_bot"` added. | B |
| C2 | `POST /api/v1/integration/telegram/webhook/<bot_token>/` | Telegram signs nothing; the only barrier was the bot token in the URL **path**, which travels in plaintext through every proxy and access log. Anyone who read one could inject conversations into a customer's assistant — burning their AI quota and poisoning their lead data. | `TelegramWebhookView._verify_secret_token` demands the `secret_token` registered via `setWebhook`, derived per bot as `HMAC(TELEGRAM_WEBHOOK_SECRET, bot_token)`. Missing header fails exactly like a wrong one. | A |
| C3 | `GET /api/v1/integration/amocrm/` | The `referer` query parameter chose the host that then received the amoCRM `client_id` / `client_secret` — an SSRF with credential exfiltration (`?referer=attacker.example`). | `AMOCRM_HOST_RE` allow-list (`<sub>.amocrm.ru|.com`) on the callback, and again on the stored subdomain in `amocrm/refresh/` and `amocrm/set-pipeline/` (old rows predate the allow-list). | A |

### High

| # | Endpoint | Issue | Fix | Pass |
|---|---|---|---|---|
| H1 | `POST /api/v1/integration/instagram/webhook/` | `X-Hub-Signature-256` verification skipped entirely when `INSTAGRAM_APP_SECRET` was unset — fail-open. | Fails closed; missing header treated as invalid. HMAC is computed over `request.body` (raw bytes), never re-serialised JSON — now proven by test. | A |
| H2 | All webhooks | Replay: a captured, correctly-signed delivery could be re-sent verbatim, answering the customer twice, re-running comment automation and re-charging AI quota. The old dedup window was 5 minutes. | `webhook_replay_seen(key)` with a 6-hour TTL, applied to `tg_dedup:<bot>:<update_id>`, `ig_dedup:<mid>`, `ig_comment_dedup:<id>`, `ig_postback_dedup:<mid>`. | A |
| H3 | Telegram webhook | Dedup key was global `tg_dedup:<update_id>`; `update_id` is a **per-bot** counter, so two bots with overlapping counters silently swallowed each other's updates. | Key scoped by `sha256(bot_token)[:16]`. | A |
| H4 | `POST amocrm/refresh/`, `POST amocrm/set-pipeline/`, `POST assistant/<pk>/billz/` | Accepted any `integration_id` / `assistant_id`: any logged-in user could mint and read another tenant's amoCRM access token, rewrite their pipeline config, or hang a Billz integration off a stranger's assistant. | Queries scoped with `Q(assistant__user=request.user) \| Q(user=request.user)` / `user=request.user`. | A |
| H5 | Instagram deauthorize / data-deletion | Deleted a customer's whole integration on an unverified `signed_request` body parameter. | `parse_meta_signed_request` verifies the HMAC and fails closed when `INSTAGRAM_CLIENT_SECRET` is missing (also de-duplicated — the closure existed verbatim in both views). | A |

### Medium

| # | Area | Issue | Fix | Pass |
|---|---|---|---|---|
| M1 | `payment/features/`, `payment/pricing-packages/` | The four `AllowAny` branches are the **public pricing page**, not a provider callback — anonymous reads are correct. But `ScopedRateThrottle` is the only global throttle class, so a view without a `throttle_scope` is completely unbounded. | `throttle_scope = "public_read"` (60/min) on all four. | B |
| M2 | `payme/get-verify-token/`, `payme/verify-code/` | Authenticated but unbounded. One makes Payme send an SMS to a card number the caller chooses; the other checks the short numeric code that comes back — an SMS pump and a code brute-force. | `throttle_scope = "payme_verify"` (10/min) on both. | B |
| M3 | `blog/` list & detail | Anonymous, search-backed, unbounded. | `throttle_scope = "public_read"`. | B |
| M4 | Landing lead notification | `full_name` / `phone_number` / `source_page` / `telegram_username` come from an anonymous public form and were interpolated into a Telegram message sent with `parse_mode=HTML` — markup and link injection into the sales team's group. | `html.escape` on every interpolated field. | B |
| M5 | All webhooks | `DATA_UPLOAD_MAX_MEMORY_SIZE` is 100 MB (for file uploads), so an anonymous caller could make the process buffer and HMAC 100 MB before the signature check could reject it. | `MAX_WEBHOOK_BODY_BYTES = 1 MB`, checked before verification → `413`. | A |
| M6 | Both Telegram + Instagram webhooks | A handler bug returned 5xx; Meta throttles then **disables** a subscription that keeps answering non-2xx, and Telegram backs the webhook off. One bug took the channel down for every customer. | `post()` wraps `_handle()` and degrades to a logged 200. Same pattern added to the lead-bot webhook. | A + B |
| M7 | `apps/integration/gateways/telegram.py`, `apps/landing/views.py` | `print()` in application code, including printing a live bot token on the "no integration found" path. | Replaced with `logger`; the bot token is logged only through `mask_secret`. | A + B |
| M8 | `apps/dashboard/views.py` | `client_full_name` / `client_phone_email` are now encrypted at rest and cannot be matched in SQL — the search silently returned nothing (and the global search `Q()` was a wasted scan). | Dropped from `search_fields` and from `DashboardGlobalSearch`. **Behavioural regression — see open items.** | A |

### Low

| # | Area | Issue | Fix | Pass |
|---|---|---|---|---|
| L1 | `apps/landing/views.py` | Bare DRF `Response` returns (CLAUDE.md §3 forbids them). | `success_response` / `error_response`. **Response shape change — see open items.** | B |
| L2 | `apps/integration/serializers.py` | A redundant `Integration.objects.get(api_token=...)` whose only branch repeated the verification directly below it, and which raised `MultipleObjectsReturned` when one bot was connected twice. | Deleted; the token is verified unconditionally. | A |
| L3 | `apps/landing/views.py` | `_handle_member_update` assigned `chat_title` and never used it. | Deleted. | B |
| L4 | amoCRM callback | Reflected the provider's `error` query string back into the response body. | Logged, not reflected. | A |

---

## 2. Verified claim: Instagram HMAC is over the raw body

The previous agent's claim checks out. `InstagramWebhookView.post` reads
`request.body` (via `webhook_body_too_large`, then `_verify_signature`) **before**
anything touches `request.data`, and hashes those exact bytes.

`test_the_signature_is_computed_over_the_raw_body_not_reserialized_json` proves
it rather than asserting it: it posts a body deliberately formatted the way
Python never would (no separator spaces, a `—` escape), first asserting that
`json.dumps(json.loads(raw)) != raw` so the two HMACs cannot coincide, then
asserting the delivery is accepted and processed. Had the code hashed
`json.dumps(request.data)`, that test would 403. No fix was needed.

---

## 3. Files changed

| File | Pass | Change |
|---|---|---|
| `apps/integration/views.py` | A | Telegram secret-token verification, IG HMAC fail-closed, `webhook_replay_seen`, body-size cap, fail-soft handlers, amoCRM SSRF allow-list + state check, amoCRM/Billz tenancy scoping, shared `parse_meta_signed_request` |
| `apps/integration/gateways/telegram.py` | A | `telegram_webhook_secret()`; `setWebhook` registers `secret_token`; `print` → `logger`; token masking |
| `apps/integration/tasks/telegram.py` | A | `Integration.assistant_for_bot_token` (encrypted-column safe); masked token logging |
| `apps/integration/serializers.py` | A | Removed the redundant/raising `Integration.objects.get(api_token=...)` |
| `apps/dashboard/views.py` | A | Dropped encrypted columns from `search_fields` / global search |
| `apps/integration/tests.py` | **B** | +36 tests (webhook authenticity, replay, degradation, amoCRM) |
| `apps/landing/views.py` | **B** | Webhook secret-token verification, no default password, `lead_bot` throttle, HTML escaping, response helpers, `logger`, fail-soft handler, dead local removed |
| `apps/landing/tests.py` | **B** | New file — 17 tests |
| `apps/payment/views.py` | **B** | `public_read` throttle ×4, `payme_verify` throttle ×2 |
| `apps/payment/tests.py` | **B** | +11 tests |
| `apps/blog/views.py` | **B** | `public_read` throttle ×2 |
| `config/settings.py` | A | Throttle scopes `oauth_callback` / `lead_bot` / `public_read` / `payme_verify`; `TELEGRAM_WEBHOOK_SECRET`, `LEAD_BOT_WEBHOOK_SECRET` (not modified in pass B) |

No model, migration or admin file was touched. `makemigrations --check
--dry-run` → **No changes detected**.

---

## 4. Tests added (64 new: 36 integration, 17 landing, 11 payment)

### `apps/integration/tests.py`

| Class | Tests | Covers |
|---|---|---|
| `TelegramWebhookSecretTokenTests` | 10 | valid secret accepted **and processed**; missing header → 403; wrong secret → 403; a secret minted for *another* bot → 403; unconfigured server key → 403; replayed `update_id` processed exactly once; two bots may share an `update_id`; Redis outage → 200, no 500; handler error → 200 but not processed; >1 MB body → 413 |
| `InstagramWebhookHardeningTests` | 11 | valid signature accepted and processed; missing `X-Hub-Signature-256` → 403; tampered signature → 403; body modified after signing → 403; **signature over raw body, not re-serialised JSON**; replayed `mid` / comment id / postback `mid` each processed once; Redis outage still delivers the comment; handler error → 200 but not processed; oversized body → 413 |
| `MetaSignedRequestTests` | 4 | valid `signed_request` removes the integration; forged signature keeps it; unconfigured app secret fails closed; data-deletion rejects an unsigned request |
| `WebhookReplayHelperTests` | 4 | first sighting vs. replay; distinct keys do not shadow; dead Redis degrades to at-least-once instead of raising; TTL outlives provider retry schedules |
| `AmoCRMCallbackTests` | 4 | foreign `referer` never receives the client secret; `amocrm.ru`-lookalike host rejected; unknown state rejected before the token exchange; provider error not reflected |
| `AmoCRMTenancyTests` | 3 | stranger cannot refresh another tenant's token; cannot repoint their pipeline; a stored non-amoCRM subdomain is refused |

### `apps/landing/tests.py` (new)

| Class | Tests | Covers |
|---|---|---|
| `LeadBotWebhookTests` | 10 | valid secret + password registers the group; missing header → 403; wrong secret → 403; unconfigured secret fails closed; wrong password (including the old repo default `repli2024`) registers nothing; unconfigured password refuses everything; a private chat cannot register itself; removal deactivates the group; handler error → 200; rate limited |
| `LandingLeadCreateTests` | 7 | lead stored and phone normalised; short phone rejected; endpoint never lists stored leads (405); Telegram notification escapes lead-supplied HTML; Telegram outage does not lose the lead; inactive group not notified; submission rate limited |

### `apps/payment/tests.py`

| Class | Tests | Covers |
|---|---|---|
| `PublicCatalogueTests` | 8 | anonymous may read the package list; retired package not exposed; payload carries no internal fields; anonymous cannot create / edit price / delete; catalogue and feature list are rate limited |
| `PaymeVerificationThrottleTests` | 3 | verify-code request and code-confirmation attempts are rate limited; both still reject anonymous callers |

> **Testing note for future work:** `override_settings(REST_FRAMEWORK=...)` does
> **not** change throttle rates. `SimpleRateThrottle.THROTTLE_RATES` is a class
> attribute bound to the rates dict at import time, so DRF's settings reload
> swaps the `api_settings` object while every throttle instance keeps reading the
> original dict. The `throttled_at()` helper in `apps/payment/tests.py` patches
> that dict instead.

---

## 5. Test result

```
$ .venv/bin/python manage.py test apps.integration apps.payment apps.landing apps.blog apps.dashboard --keepdb
/home/shahzod/mywork/aylo-backend/.venv/lib/python3.12/site-packages/pydub/utils.py:170: RuntimeWarning: Couldn't find ffmpeg or avconv - defaulting to ffmpeg, but may not work
  warn("Couldn't find ffmpeg or avconv - defaulting to ffmpeg, but may not work", RuntimeWarning)
Using existing test database for alias 'default'...
Found 158 test(s).
System check identified no issues (0 silenced).
..............................................................................................................................................................
----------------------------------------------------------------------
Ran 158 tests in 1.097s

OK
Preserving test database for alias 'default'...
```

```
$ .venv/bin/python manage.py makemigrations --check --dry-run
No changes detected
```

Baseline before this session was 69 integration tests; the suite across the five
apps is now 158.

---

## 6. Open items needing a human decision

### 6.1 Deployment is a two-step migration — webhooks must be re-registered

**This is not a code change you can just ship.** `TelegramWebhookView` now
*rejects every update* that does not carry the right secret token, and Telegram
only sends that header for webhooks registered **with** `secret_token`. Existing
registrations were created without it.

Required order:

1. Provision `TELEGRAM_WEBHOOK_SECRET` (any high-entropy string) **before**
   deploying. With it unset the webhook fails closed and **every customer's
   Telegram bot goes silent**.
2. Deploy.
3. Re-run `setWebhook` for **every existing Telegram integration** —
   `set_telegram_webhook(bot_token, url)` now attaches
   `secret_token = HMAC(TELEGRAM_WEBHOOK_SECRET, bot_token)`. Until a bot is
   re-registered, its updates are rejected with 403. There is no management
   command for this yet; **someone must decide whether to write one or to
   re-register from a shell.**
4. Same for the landing lead bot: provision `LEAD_BOT_WEBHOOK_SECRET` and
   re-register that webhook with it.

Rotating `TELEGRAM_WEBHOOK_SECRET` later means re-registering every bot again.

### 6.2 Secrets that must exist in production

| Variable | Consequence if unset |
|---|---|
| `TELEGRAM_WEBHOOK_SECRET` | Every Telegram update rejected (403) |
| `LEAD_BOT_WEBHOOK_SECRET` | Lead-bot webhook rejects everything; groups cannot be registered |
| `LEAD_BOT_PASSWORD` | **No default any more** — group verification always refused. The old default `repli2024` is in git history and must be treated as public; pick a new value |
| `INSTAGRAM_APP_SECRET` | Every Instagram delivery rejected (403) |
| `INSTAGRAM_CLIENT_SECRET` | Deauthorize / data-deletion callbacks rejected |
| `AMOCRM_SECRET_KEY` | amoCRM OAuth returns 500 |

`.env.example` documents only `INSTAGRAM_*`. It is owned by another workstream
this session, so **the four missing variables above still need to be added
there.**

### 6.3 Breaking API change — landing lead response shape

`POST /api/v1/landing/lead/` previously returned the bare body
`{"message": "...", "id": "<uuid>"}`. To comply with CLAUDE.md §3 it now returns
the standard envelope:

```json
{"success": true, "code": 201, "message": "...", "data": {"id": "<uuid>"}}
```

The 400 case likewise moved from bare `serializer.errors` to
`{"success": false, ..., "data": {<field errors>}}`. **The landing site reads
this response and needs a coordinated update** — or tell me to revert this one
item and keep the legacy shape.

### 6.4 No provider signature exists for these callbacks

| Callback | What the provider actually offers | Current control |
|---|---|---|
| Telegram (`/telegram/webhook/`, `/lead-bot/webhook/`) | **Nothing signed.** `secret_token` echoed in a header is the only mechanism Telegram supports | Secret token + fail-closed. This is the strongest control available |
| amoCRM OAuth (`/amocrm/`) | **No signature.** amoCRM redirects a browser with `code` / `state` / `referer` | Single-use 5-min `state` in Redis, `amocrm.(ru\|com)` host allow-list, `oauth_callback` throttle (20/min) |
| Instagram OAuth (`/instagram/callback/`) | **No signature.** | `oauth_callback` throttle only. **Unresolved:** `assistant_id` still arrives as an unauthenticated query parameter. It is now resolved and ownership-checked *when a session is present*, but the anonymous case cannot be bound without a signed `state` in the authorize URL. That is a design change someone needs to sign off on |

Instagram DM/comment webhooks and Meta deauthorize/data-deletion **do** have real
signatures (`X-Hub-Signature-256`, `signed_request`) and both are verified.

**No payment-provider callback exists in this codebase.** All four `AllowAny`
branches in `apps/payment/views.py` are the public pricing catalogue; the Payme
integration is entirely outbound (this server calls Payme). If an inbound Payme
Merchant API endpoint is ever added it will need Payme's `Authorization: Basic`
merchant-key check — do not ship it without one.

### 6.5 Dashboard search regression (from pass A)

Dashboard conversation search and global search no longer match
`client_full_name` or `client_phone_email` — those columns are encrypted at rest
and cannot be matched in SQL. Support staff searching a customer by name or
phone now get nothing. Restoring it needs a deterministic blind-index column
(the `*_hash` pattern already used for `api_token`). **Product call: is
name/phone search required by support?**

### 6.6 Smaller items

- `notify_telegram_groups` still runs **synchronously inside the public lead
  request**, doing one blocking HTTP call per group (5 s timeout each). It should
  move to Celery; `apps/landing/` has no tasks module yet, so that was left out
  of this change.
- Instagram webhook `_handle` processes only `entry[0]` and logs a warning when
  Meta batches more. Batched deliveries are silently dropped past the first —
  pre-existing, unchanged, worth a follow-up.
- `webhook_replay_seen` is best-effort: on a Redis outage it degrades to
  at-least-once. For Telegram the whole message pipeline is Redis-backed, so an
  outage means the update is acknowledged but not processed (covered by
  `test_a_redis_outage_still_delivers_the_update`). That is a deliberate
  trade-off, not a bug — but it means a Redis outage silently loses Telegram
  messages, which should be alerted on.
