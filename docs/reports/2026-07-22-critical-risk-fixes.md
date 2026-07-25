# Change Report — Critical-risk fixes (steps 1–5 of the fix plan)

**Date:** 2026-07-22
**Scope:** executes the prioritized fix plan from
`2026-07-22-critical-risk-investigation.md`. Items needing a product decision
(H6, M2, M9) and the Meta-side secret rotation were **not** done here — see
"Deployment prerequisites" and "Open items".

---

## ⚠️ Deployment prerequisites (read before deploying)

The app now **fails closed**, so these env vars must be set in every environment:

| Env var | What happens if missing |
|---|---|
| `SECRET_KEY` | App refuses to boot when `DEBUG` is off (previously fell back to a key committed in git → forgeable JWTs) |
| `INSTAGRAM_APP_SECRET` | All Instagram webhook POSTs are rejected with 403 (previously accepted unsigned) |
| `INSTAGRAM_VERIFY_TOKEN` | Meta's webhook GET handshake fails (previously had a hardcoded fallback) |
| `INSTAGRAM_CLIENT_SECRET` | Instagram token exchange fails with a logged error (previously used a hardcoded secret) |
| `ALLOWED_HOSTS` (optional) | Defaults to `.repli.uz,localhost,127.0.0.1` — set explicitly if the API is served on another hostname |

**Still on you:** rotate the leaked Meta app secret (`dc12…8f4f`) in the Meta
dashboard — it lives in git history forever. Verify the env
`INSTAGRAM_CLIENT_SECRET` is the (new) correct secret for the token-exchange call.

---

## Fixes

### 🔴 Critical

| # | Issue | Fix |
|---|---|---|
| S1 | Instagram app secret hardcoded in `shared/addons/instagram.py` | Uses `settings.INSTAGRAM_CLIENT_SECRET`; logs and returns `None` if unset. Hardcoded `INSTAGRAM_VERIFY_TOKEN` fallback removed from settings |
| S2 | `SECRET_KEY` fell back to a committed value | Hard-fails (`ImproperlyConfigured`) when env is missing and `DEBUG` is off; dev/test keep a clearly-labeled dev key |
| P1 | Card delete IDOR (`CardRemoveView`) | `Card.objects.get(id=…, user=request.user)` |
| P2 | Default-card IDOR (`SetDefaultCard`) | Same `user=user` scoping |
| P3 | Cross-tenant retry-payment read | Filter adds `subscription__users=request.user` |
| — | (found while fixing) `SubscriptionUpdateAutoRenewView` had an unscoped queryset — any user could flip any subscription's auto-renew | Queryset scoped to `Subscription.objects.filter(users=request.user)` |
| A1 | `MessageListCreateView` / conversation POST were `AllowAny` | Both require `IsAuthenticated`; create verifies the target belongs to the caller (404 otherwise) |
| A2 | IDOR across conversation/message/lead/settings/file/export views | New `owned_assistants(user)` helper; **every** assistant-app view now filters through it. `ConversationRetrieveView` returns 404 instead of 500 for unknown ids. Also fixes the `Q(user=None)` orphan-assistant leak in the old ownership pattern (Assistant.user is nullable) |
| C4 | `MessageRetrieveView` had `queryset = Assistant.objects.all()` | Now `Message.objects` scoped by ownership |

### 🟠 High

| # | Issue | Fix |
|---|---|---|
| H1 | Google OAuth linked accounts on an unverified email claim | Email is only used for matching/linking when `email_verified is True`; unverified emails are not stored on the new account either |
| H2 | `ALLOWED_HOSTS = ["*"]` | Env-driven, defaults to `.repli.uz,localhost,127.0.0.1` |
| H3 | Instagram webhook signature check failed open | Fails closed with a loud log; GET handshake also rejects when the verify token is unconfigured |
| H4/M7 | `print()` of webhook payloads, API responses, SMS responses, and **access/refresh tokens** (amoCRM, Instagram, Billz) | All ~50 prints removed or converted to lazy `logger` calls; token/secret values are never logged (status codes only) |
| H5 | Internal error details returned to clients (`str(e)`, `response.text`) | Generic client messages; details go to `logger.exception` server-side (Google callback + 5 amoCRM views) |
| M8 | `search_fields`/`ordering_fields` on nonexistent columns (`session_id`, `message`) → 500 | Point at real columns (`username`, `message_content`) |

Also fixed along the way: `MessageBulkReadView` crashed with `AttributeError`
when a conversation had no messages (`last_message.conversation` on `None`) —
now guarded; dead imports/commented-out code removed in every touched file
(including the unused `sentry_sdk` import in settings).

## Files changed

| File | Change |
|---|---|
| `config/settings.py` | S2 hard-fail, H2 ALLOWED_HOSTS, verify-token fallback removed, dead sentry import removed |
| `apps/shared/addons/instagram.py` | S1 env secret, print→logger (no bodies/tokens), dead `re` import |
| `apps/payment/views.py` | P1/P2/P3 + auto-renew scoping, dead imports |
| `apps/assistant/views.py` | `owned_assistants()` helper; A1/A2/C4/M8 scoping + auth on all views; bulk-read guard; prints removed |
| `apps/user/views.py` | H1 email_verified, H5 generic error + `logger.exception`, dead imports |
| `apps/integration/views.py` | H3 fail-closed signature + handshake, H4 print sweep, H5 generic amoCRM errors, dead imports/duplicate block |
| `apps/shared/addons/verification.py` | M7 SMS prints→logger (status only), dead imports |

## Tests

19 new tests, all regressions for the above:

- `apps/payment/tests.py` — `CardScopingTests`, `RetryPaymentScopingTests`, `AutoRenewScopingTests` (P1–P3 + auto-renew)
- `apps/assistant/tests.py` — `EndpointScopingTests` (A1 anonymous 401s, A2 cross-tenant 404s/empty lists, owner still works, export-leads scoped)
- `apps/integration/tests.py` — `InstagramWebhookSignatureTests` (missing secret 403, bad signature 403, valid signature 200, handshake fail-closed)
- `apps/user/tests.py` — `GoogleOAuthEmailVerificationTests` (unverified email doesn't link, verified email still does)

```
Ran 122 tests in 5.578s
OK
```

(103 pre-existing + 19 new, `manage.py test --keepdb`.)

## Open items needing a human decision

1. **Rotate the Meta app secret** (S1) — requires Meta dashboard access. Mandatory.
2. **H6** — should customer-created `staff` users pass `IsDashboardUser`? (unchanged)
3. **M2** — 7-day access-token lifetime (unchanged).
4. **M9** — dedicated Payme/billing-callback security review (not started).
5. **Was the `AllowAny` conversation/message POST serving a public website
   widget?** If yes, it needs a proper widget auth token — the endpoints now
   require a logged-in user, which would break an unauthenticated widget.
6. Remaining mediums from the investigation: M1 (XFF spoofing), M3 (broadcast
   retry idempotency), M4 (lead-export temp file), M5 (OTP compare), M6 (HSTS).
