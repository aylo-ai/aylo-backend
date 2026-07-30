# Investigation Report — Critical risks across the whole codebase

**Date:** 2026-07-22
**Scope:** platform config (`config/`), secrets, auth (`apps/user`), payments
(`apps/payment`), webhooks & integrations (`apps/integration`), assistant pipeline
(`apps/assistant` — builds on the 2026-07-21 investigation), dashboard, logging/PII,
Celery/Redis infra.
**Status:** investigation only — no fixes applied in this pass (except where noted
as already fixed earlier today). Prioritized fix plan at the end.

---

## 🔴 Critical

### S1. Instagram app secret hardcoded in source
`apps/shared/addons/instagram.py:23`
```python
CLIENT_SECRET = "dc12159193e69625fd27281997b28f4f"
```
A live Meta app secret committed to git. Anyone with repo access (or the git
history, forever) can mint long-lived Instagram tokens for the app.
**Action: rotate the secret at Meta, move to `os.environ`, purge is optional but
rotation is mandatory.** Same class of issue: `INSTAGRAM_VERIFY_TOKEN` has a
hardcoded fallback in `config/settings.py:390` (`"wqbm2DoK5zfsF28Qb82Z"`).

### S2. `SECRET_KEY` falls back to a value committed in git
`config/settings.py:14` — `os.environ.get("SECRET_KEY", "django-insecure-…")`.
`SIGNING_KEY` for JWT is this key (`settings.py:230`). If the env var is ever
missing in production, **every JWT is forgeable by anyone reading the repo** —
full account takeover of any user, silently. Should hard-fail on missing env in
production instead of falling back.

### P1. Card IDOR — any user can delete any other user's card
`apps/payment/views.py:223` (`CardRemoveView`): `Card.objects.get(id=card_id)`
with **no `user=request.user` filter**. Any authenticated user who obtains a card
UUID can delete another user's card **and de-tokenize it in Payme**
(`remove_payme_card`) — breaking the victim's auto-renew billing.

### P2. Card IDOR — any user can flip another user's default card
`apps/payment/views.py:134` (`SetDefaultCard`): same unscoped
`Card.objects.get(id=card_id)`. Cross-tenant mutation of billing state; response
also echoes the victim's masked card number.

### P3. Cross-tenant read of payment retries
`apps/payment/views.py:345` (`RetryPaymentListView`): filters only by
`subscription_id` from the URL — no ownership check. Any authenticated user can
enumerate another tenant's failed-payment history.

### A1. Unauthenticated message create/list still open (C3, 2026-07-21)
`apps/assistant/views.py:168` — `MessageListCreateView` is `AllowAny`: anyone can
POST messages into any conversation (runs the agent → **burns the owner's paid
request quota**) and read any conversation's history. `ConversationListCreateView`
POST is also `AllowAny` (`views.py:114`). Confirmed still unfixed today.

### A2. IDOR on conversations / leads still open (C2, 2026-07-21)
Conversation/lead/message detail views fetch by `pk` with no tenant scoping;
`ExportLeadsView` dumps leads for any `assistant_id`. Confirmed still unfixed.

---

## 🟠 High

### H1. Google OAuth links accounts without checking `email_verified`
`apps/user/views.py:337` — lookup `Q(sub=sub) | Q(email=email)` trusts the email
claim from the ID token but never checks `user_info.get("email_verified")`.
An attacker with a Google identity carrying an **unverified** email equal to a
victim's account email gets logged in as (and permanently `sub`-linked to) the
victim. State-CSRF and token signature *are* handled correctly; this is the one
remaining takeover vector.

### H2. `ALLOWED_HOSTS = ["*"]`
`config/settings.py:17`. Host-header injection: any absolute URL the app builds
from the request (OAuth redirects, links in emails) can be attacker-controlled.
Pin to the real domains (CORS/CSRF lists at `settings.py:182/216` already know them).

### H3. Instagram webhook signature check fails open
`apps/integration/views.py:180` — `if not app_secret: return True`, and
`INSTAGRAM_APP_SECRET` defaults to `""` (`settings.py:391`). If the env var is
unset, **anyone can POST forged webhook events**, driving the AI (token burn),
comment replies and DMs. Should fail closed (reject) or at minimum log loudly.

### H4. Webhook payloads printed to stdout (PII + CLAUDE.md violation)
`apps/integration/views.py` `InstagramWebhookView.post` uses `print()` for the
full webhook body (client IDs, message text). Bypasses logging config entirely —
lands in container stdout. Same pattern in `shared/addons/instagram.py`
(`send_message`, `send_private_reply`, `send_postback` print full API responses).

### H5. Internal error details returned to clients
Multiple `except Exception as e: return error_response(message=str(e))` — e.g.
`GoogleAuthCallbackView` (`user/views.py:361`), several amoCRM views. Leaks
stack-level details (paths, provider errors) to the caller. Return a generic
message, log the detail server-side.

### H6. Dashboard privilege breadth
`IsDashboardUser` (super_admin/admin/manager/support_agent/**staff**) guards ~35
read endpoints in `apps/dashboard/views.py`, including full user lists with
contact details and subscription/finance data. A customer-created **staff**
account (created via `AddStaffView` by any customer!) has `user_role=staff` — and
therefore passes `IsDashboardUser`. **Customer-created staff can read the entire
platform's user base.** Verify intent; likely needs a separate role or an
`is_platform_staff` distinction.

---

## 🟡 Medium

| # | Issue | Where |
|---|---|---|
| M1 | Audit-log IP taken from spoofable `X-Forwarded-For` (first value, client-controlled) | `apps/dashboard/views.py:63` |
| M2 | JWT access-token lifetime 7 days (long window for a stolen token; refresh rotation+blacklist are correctly on) | `settings.py:224` |
| M3 | `send_broadcast_task` has no lock/idempotency — a retry (max_retries=2) after partial send **re-sends the whole broadcast** from scratch | `apps/integration/tasks/broadcast.py` |
| M4 | Lead export writes `leads_export_<date>.xlsx` to CWD, never cleaned, fixed per-day name → concurrent overwrite (C5, still open) | `apps/assistant/serializers.py:528` |
| M5 | OTP compared with `==` (non-constant-time). Mitigated by the 5-attempt cap + 60s TTL — low practical risk, cheap to fix with `hmac.compare_digest` | `shared/addons/verification.py:107` |
| M6 | `HSTS_SECONDS = 3600` — too short to be meaningful (recommend ≥ 31536000 once stable) | `settings.py:178` |
| M7 | SMS provider raw response printed (`print`) incl. phone-adjacent data | `shared/addons/verification.py:68` |
| M8 | `search_fields`/`ordering_fields` referencing nonexistent columns → 500s (H2, 2026-07-21, still open) | `apps/assistant/views.py:107,165` |
| M9 | Payme webhook/`PaymeCallBackAPIView`-style flows not deeply audited this pass — **needs its own review** (amount tampering, idempotency, signature) | `apps/payment/` |

---

## ✅ Verified healthy (worth knowing)

- **OTP flow**: 60s code TTL, 5-attempt cap tied to code lifetime, send/verify
  throttles (`otp_send` 5/min, `otp_verify` 10/min). Solid.
- **Google OAuth**: one-time Redis-backed `state` (CSRF-safe), ID-token signature/
  audience/expiry verified via `google_id_token.verify_oauth2_token` (only the
  `email_verified` gap above).
- **Logout**: refresh-token blacklist active (`token_blacklist` app installed,
  `BLACKLIST_AFTER_ROTATION=True`).
- **Telegram webhook**: token-in-path checked against DB, Redis dedup by
  `update_id`.
- **amoCRM OAuth callback**: `AllowAny` but protected by one-time Redis state.
- **Cards/Transactions list views**: correctly scoped to `request.user`
  (`CardListView`, `TransactionListView`, `CardDetailView` — the *list/detail*
  side is fine; only the two mutations in P1/P2 are unscoped).
- **Quota charging** (C1): fixed today — `None`-guarded, charge-once, race-free
  `F()` decrement (see `2026-07-21-assistant-c1-message-quota-crash.md` update).
- **Celery**: task names pinned, routing/beat verified against the registry,
  `acks_late` + `reject_on_worker_lost` on.

---

## Prioritized fix plan

| Order | Items | Effort | Why first |
|---|---|---|---|
| 1 | **S1** rotate + env-ify Instagram secret; **S2** fail-hard SECRET_KEY | tiny | public-in-git credentials |
| 2 | **P1, P2, P3** add `user=request.user` scoping (3 one-line filters + tests) | small | live cross-tenant billing mutations |
| 3 | **A1, A2** auth + tenant-scope the assistant endpoints (yesterday's C2/C3) | medium | unauthenticated quota burn + data read |
| 4 | **H1** require `email_verified`; **H3** fail-closed webhook signature; **H2** pin `ALLOWED_HOSTS` | small | account takeover / forged events |
| 5 | **H4, H5, M7** print→logger sweep in views/addons; generic client errors | small | PII hygiene (pattern already applied to `shared/addons/utils.py` today) |
| 6 | **H6** decide staff-role model (needs product decision) | discussion | privilege design |
| 7 | **M1–M9** as capacity allows; **M9 (Payme flow audit)** deserves a dedicated pass | varies | |

## Open items needing a human decision

1. **H6** — should customer-created `staff` users really pass `IsDashboardUser`?
2. **M2** — acceptable access-token lifetime (7d ↔ shorter + refresh)?
3. **S1** — who rotates the Meta app secret and when (requires Meta dashboard access)?
4. **M9** — schedule the dedicated Payme/billing-callback security review.
