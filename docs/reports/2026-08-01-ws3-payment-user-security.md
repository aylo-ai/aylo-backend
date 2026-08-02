# 2026-08-01 — WS-3 security audit: `apps/payment/**`, `apps/user/**`

Workstream WS-3 of `docs/reports/2026-08-01-work-board.md`. Scope: money and
identity. Owned trees: `apps/payment/**`, `apps/user/**`, additive changes to
`apps/shared/permissions.py`, review-only on `config/settings.py`.

**Headline:** the worst defect was not an IDOR on a card or a transaction. Every
card/transaction route named on the work board was already scoped (the
2026-07-22 pass did that work — see "Findings that did not survive scrutiny").
The real hole was one line in `apps/shared/permissions.py`: **any customer could
mint themselves a platform-admin-console token in two HTTP requests.**

---

## Critical

### C-1 — Customer → platform-admin escalation via `POST /api/v1/user/add-staff/`

| | |
|---|---|
| Actor | Any self-signed-up `customer` (phone OTP registration is open) |
| Root cause | `UserRoles.STAFF` was a member of `DASHBOARD_ROLES` |
| Files | `apps/shared/permissions.py` |

**Exploit path**

1. Sign up normally: `POST /api/v1/user/auth/send-otp/` → `.../verify-otp/`.
   New accounts default to `user_role = customer`.
2. `POST /api/v1/user/add-staff/` with
   `{"first_name":"a","last_name":"b","email_or_phone_number":"me2@example.com"}`.
   `AddStaffView` is gated by `IsAdminOrCustomer`, so a customer passes.
   `AddStaffSerializer` hard-codes `user_role = UserRoles.STAFF.value`, and its
   `to_representation()` puts **that new account's JWT in the 201 body**.
3. Replay that access token against the admin console:

   ```
   GET /api/v1/dashboard/users/        → every account: username, email, phone, role
   GET /api/v1/dashboard/cards/        → every saved card on the platform
   GET /api/v1/dashboard/transactions/ → every transaction, with the payer embedded
   GET /api/v1/dashboard/balances/     → every balance
   GET /api/v1/dashboard/search/       → cross-tenant global search
   GET /api/v1/dashboard/conversations/, /leads/, /messages/, /integrations/
   ```

   All of these are `permission_classes = [IsDashboardUser]` over an unscoped
   `Model.objects.all()`. `staff ∈ DASHBOARD_ROLES` meant the forged token
   passed every one of them.

Revoking the token does not help either: the attacker can pick a phone number
they control, and `DashboardSendOtpLoginView` explicitly admits any phone whose
`user_role in DASHBOARD_ROLES`, so the account could be re-authenticated at
will. The role membership was the vulnerability, not the token handout.

**Why `staff` is not a console role.** `grep -rn STAFF apps/` returns exactly
four sites: the enum, `AddStaffSerializer` (which mints it), `StaffListView` /
`StaffDeleteView` (which list a *customer's own* employees, scoped by
`created_by=request.user`), and `DASHBOARD_ROLES`. Nothing in the codebase ever
assigns `staff` to an internal operator. Every `staff` row in the database is a
tenant's employee, created by that tenant. The internal console roles are
`super_admin`, `admin`, `manager`, `support_agent`.

**Fix.** `UserRoles.STAFF.value` removed from `DASHBOARD_ROLES`, with the
reasoning recorded inline. This is the only change made to
`apps/shared/permissions.py`; no class was renamed, altered or removed, so
concurrent workstreams that import from it are unaffected. **Flagged as an open
item below** — if any real internal operator was ever given `user_role='staff'`
in production, they lose console access and must be moved to `support_agent`.

---

## High

### H-1 — A Payme card token from anywhere binds the card to whoever posts it

| | |
|---|---|
| Actor | Any authenticated user holding a Payme card token |
| Root cause | `CardCreateSerializer` asked Payme "is this token live?" but never "is it the caller's?", and echoed the token back in its own response |
| Files | `apps/payment/serializers.py` |

**Exploit path**

`POST /api/v1/payment/payme/card/add/` accepts `card_token` straight from the
request body. `validate_card_token()` calls Payme `cards.check`, which only
answers *is this token live and rebillable* — it has no concept of "the caller".
On success a `Card` row is created with `user = request.user`.

`Card.card_token` has no uniqueness constraint, so the victim's own row survives
untouched and nothing looks wrong from either side. Downstream,
`PayWithCardSerializer.validate()` authorises purely on the **local**
`Card.objects.filter(id=card_id, user=user)` row and then charges
`card.card_token`. So:

> attacker POSTs the victim's token → owns a `Card` row → `POST
> /api/v1/payment/payme/card/pay-subscription/` → **the victim's real card pays
> for the attacker's subscription**, and the resulting `Transaction` is filed
> under the attacker.

The token is not hard to come by, because this same endpoint **returned it in
its 201 body** (`card_token` was in `fields`, and the view responds with
`serializer.data`). A chargeable payment credential in a response body reaches
browser devtools, HAR captures, reverse-proxy access logs, analytics/session
replay and mobile crash reports. `POST /payment/payme/get-verify-token/` returns
a token in plaintext too.

**Fix (two parts, both at the root):**

1. `card_token` is now `write_only`. **This is a response-shape change and it is
   the fix — call it out to the frontend:** `POST /payment/payme/card/add/` no
   longer returns `card_token`. Nothing in this repo consumed it; the client
   already has the value it just sent.
2. A token already attached to a *different* user is refused with a 400 before
   Payme is even called. This closes the concrete replay above. It is not a
   complete defence — it cannot help when the victim has not saved the card
   locally yet — see open items for the durable fix (a `unique` constraint plus
   binding tokens to the caller at mint time).

**Bug fixed in passing:** `card_number` and `expiry_date` were writable and, as
non-nullable model fields, *required* — the endpoint rejected a body that did
not carry them, then discarded them in favour of Payme's values. They are now
`read_only`, so the request body is just `{card_token, name?, color?}`.

### H-2 — No rate limit on any endpoint that spends money or sends an SMS

| | |
|---|---|
| Actor | Any authenticated user (H-2a needs only an account) |
| Root cause | `DEFAULT_THROTTLE_CLASSES = [ScopedRateThrottle]` is a silent no-op on any view that declares no `throttle_scope`, and no payment view declared one |
| Files | `apps/payment/views.py`, `apps/user/views.py`, `config/settings.py` |

**H-2a, the sharp one.** `POST /api/v1/payment/payme/get-verify-token/` takes a
`number` + `expire` the caller types and calls Payme `cards.create` followed by
`cards.get_verify_code`. Payme sends that verification SMS **to the phone
registered against the card — a third party's phone, not the caller's.** A
single authenticated account could therefore:

- SMS-bomb any card holder whose PAN the attacker knows, at this merchant's cost;
- use `cards.create`'s error/no-error split as a **PAN + expiry validity oracle**,
  enumerating card numbers offline-style against a real issuer;
- burn the merchant's Payme API quota.

**H-2b.** `payme/verify-code/` guesses a 6-digit code against a card token with
unlimited retries. `payme/card/add/`, `card/pay-subscription/`,
`card/update-subscription/`, `manual-payment/` and `cards/<pk>/remove/` all make
outbound Payme calls per request with no ceiling.

**H-2c.** `POST /auth/register/` (account creation) and `POST /auth/login/refresh/`
(unauthenticated, mints an access+refresh pair) were unthrottled. Only
`otp_send`, `otp_verify`, `landing_lead` and the dashboard login had limits.

**Fix.** Scopes added to the views plus rates in `config/settings.py` — the one
edit made to that file, and unavoidable: `ScopedRateThrottle` raises
`ImproperlyConfigured` if a scope has no rate, so the view annotation and the
rate table must land together. No existing rate was changed.

| Scope | Rate | Endpoints |
|---|---|---|
| `payment_card` | 10/min | `payme/card/add/`, `payme/get-verify-token/`, `payme/verify-code/`, `cards/<pk>/remove/` |
| `payment_charge` | 5/min | `payme/card/pay-subscription/`, `payme/card/update-subscription/`, `manual-payment/` |
| `auth_register` | 10/min | `auth/register/` |
| `token_refresh` | 20/min | `auth/login/refresh/` |

---

## Medium

### M-1 — A client could declare its own card "verified"

`CardSerializer` (behind `PATCH /api/v1/payment/cards/<pk>/`) had `is_verified`
and `card_number` writable. `is_verified` is a **security gate**: both
`PayWithCardSerializer.validate()` and `billing.process_subscription_payment()`
refuse to charge a card unless it is set. A client that can PATCH it decides for
itself whether its own card counts as verified, and
`process_subscription_payment` picks its charge target with
`user.cards.filter(is_verified=True, is_default=True).first()` — so the flag
also steers which card the *automatic renewal* bills.

`card_number` is the masked PAN rendered against transactions and in the
dashboard; a client-set value misrepresents which card a token actually charges
(user sees "…1234", token bills a different card).

**Fix.** Both are `read_only` on `CardSerializer` now — only Payme sets them.
Writable fields on a card PATCH are `name`, `color`, `is_default`, `expiry_date`.
**Response shape is unchanged; request handling is:** PATCHing `card_number` or
`is_verified` is now silently ignored rather than applied.

### M-2 — Internal exception text returned to the caller

`PayWithCardSerializer.create()` ended with
`raise_validation_error(message=_("To'lov jarayonida xatolik yuz berdi: {}").format(str(e)))`,
where `e` is *any* exception from a ~40-line `try` covering Payme HTTP calls,
`Transaction` writes and subscription updates — a database error, an
`AttributeError`, or a library message carrying internals, all handed to the
client. Now logged with `logger.exception` and the caller gets the plain message.
The msgid lost its `{}`; all five catalogs updated accordingly.

---

## Low

| # | Finding | Action |
|---|---|---|
| L-1 | **Latent unscoped class-level querysets.** 8 of the 9 `X.objects.all()` lines on the work board were dead attributes shadowed by an overriding handler; the 9th (`NotificationListView`) was read by a scoped `get_queryset()`. Not exploitable — but they are the exact shape that *becomes* an IDOR the moment someone deletes a hand-rolled `get_object()`/`delete()` override. | Replaced with scoped `get_queryset()` (`CardDetailView`, `CardRemoveView`, `NotificationListView`) or deleted where the view is a pure `CreateAPIView` (`CardCreateWithPaymeView`, `UserRegisterView`, `AddStaffView`) or already had one (`TransactionListView`, `RetryPaymentListView`, `UpdateProfileView`). Tenancy now lives in one place per view instead of in the handler body. |
| L-2 | **`TransactionListView` ownership branch is inverted.** `if user.created_by: return Transaction.objects.filter(user__created_by=user)`. A user who *has* a creator (an employee) is shown the transactions of users *they* created — and `AddStaffView` forbids employees creating employees, so that is always the empty set, and they never see their own. The branch meant to widen an owner's view to their employees' transactions never fires. | **Not fixed.** Strictly *narrower* than intended, so it leaks nothing; correcting it would widen access, which is a behaviour change this workstream is not authorised to make. Open item. |
| L-3 | `PayWithCardSerializer.payment_method` is a free `CharField` written to `Transaction.payment_method`, bypassing the `PaymentMethods` choices. Garbage in a money record. | Reported only — it is a data-integrity defect, not a boundary. |
| L-4 | `UpdateProfileSerializer` declares `phone_number` writable, but `update()` only assigns `first_name`/`last_name`/`username`, so it is silently dropped. The API says it accepted a login-identifier change it did not make. | Reported only — the current behaviour is the safe one; making the contract honest is a product decision. |
| L-5 | `BalanceSerializer` has writable `user` and `amount`, but is only ever bound to read-only list views. Latent. | Reported only. |

---

## `config/settings.py` review (no unilateral change)

### JWT — `SIMPLE_JWT`, lines ~252-275

```python
"ACCESS_TOKEN_LIFETIME": timedelta(days=7),
"REFRESH_TOKEN_LIFETIME": timedelta(days=30),
"ROTATE_REFRESH_TOKENS": True,
"BLACKLIST_AFTER_ROTATION": True,
```

**Left unchanged — this is an operational decision.** The risk, stated plainly:

- Rotation + blacklist protects the *refresh* token. **The access token has no
  revocation path at all** — it is a self-contained bearer credential valid for
  7 days. `LogoutView` blacklists the refresh token only, so "log out on the
  stolen laptop" leaves the attacker a working session for up to a week.
- Same window applies to a **role demotion**: `DashboardUserChangeRole` writes
  the new role to the database, but a live access token minted before the change
  keeps asserting the old `user_id` and re-reads the role per request — so that
  one is fine — while a token stolen from a *former* admin stays valid until it
  expires. C-1 above would have had a 7-day tail even after the fix, for any
  token already minted.
- Deactivation *is* covered: `default_user_authentication_rule` checks
  `is_active` on every request.
- Recommendation: 15–60 minutes for `ACCESS_TOKEN_LIFETIME`. The refresh flow
  already exists (`/auth/login/refresh/`, now throttled), so clients should
  absorb it; the cost is one extra round-trip per hour per client.

### Other settings, all clean

- `SECRET_KEY`, `PAYME_ID`, `PAYME_KEY`, `EMAIL_HOST_PASSWORD`, Google OAuth
  secrets: all `os.environ`, and `SECRET_KEY` raises `ImproperlyConfigured` when
  `DEBUG` is off. No committed credential.
- `EMAIL_BACKEND` defaults to real SMTP, so the OTP email body does not land in
  application logs by default.
- `apps/shared/addons/verification.py` audited line by line: the OTP code is
  never passed to `logger` on any path — send, verify, failure, or the attempt
  counter. Failed SMS delivery logs the provider's status code only.

### There is no inbound payment callback to harden

The brief asked for signature/constant-time verification on payment callbacks.
`grep -rn "CheckPerformTransaction|Paycom|callback"` over `apps/` finds no Payme
merchant-API receiver: every Payme interaction in this codebase is **outbound**
(`apps/payment/services/billing.py`), authenticated with an `X-Auth` header. So
there is no unauthenticated payment surface, no `==` on a secret, and no replay
window. The only inbound callbacks are Google OAuth (`state` verified against
Redis and consumed atomically — already correct) and the Instagram/Telegram
webhooks, which belong to WS-4.

### `AllowAny` surfaces in scope — all legitimate

| Endpoint | Verdict |
|---|---|
| `GET /payment/features/`, `/pricing-packages/` (list + detail) | Public pricing page. Writes correctly gated by `IsAdmin` via `get_permissions()`. `get_permissions()` assigning `self.permission_classes` is per-request (Django builds a fresh view instance per call), so it does not leak across requests. |
| `GET /user/privacy-policy/`, `/user-agreement/` | Public legal documents. |
| `POST /user/auth/send-otp/`, `/verify-otp/` | Public by necessity; throttled, and `verification.py` caps wrong guesses at 5 before burning the code. |
| `POST /user/auth/register/` | Public, but gated on a Redis `{identifier}_verified` marker that only a completed OTP sets — it verifies something the caller did not supply. Now throttled. |
| `POST /user/auth/login/refresh/` | Public by necessity (bearer of a refresh token); signature + blacklist checked. Now throttled. |
| `GET /user/accounts/google/login/callback/` | `state` issued into Redis with a 600s TTL and consumed with `delete()` (atomic, single-use); ID token verified via `verify_oauth2_token` for signature/issuer/audience/expiry; account linking requires `email_verified is true`. Correct. |

---

## Findings that did not survive scrutiny

Recorded so the next audit does not re-open them. Each of the "unscoped
queryset" lines named on the work board was checked against its handler:

| Line | Verdict |
|---|---|
| `payment/views.py:140` `CardCreateWithPaymeView` | `CreateAPIView`; the attribute was never read. Deleted. |
| `payment/views.py:186` `CardDetailView` | `get_object()` already filtered `user=self.request.user`. Now a scoped `get_queryset()`. |
| `payment/views.py:250` `CardRemoveView` | `delete()` already filtered by owner. Now a scoped `get_queryset()`. |
| `payment/views.py:369` `TransactionListView` | `get_queryset()` overrode it (see L-2). Attribute deleted. |
| `payment/views.py:383` `RetryPaymentListView` | `get_queryset()` filtered `subscription__users=self.request.user`. Attribute deleted. |
| `user/views.py:91` `UserRegisterView`, `:376` `AddStaffView` | `CreateAPIView`; never read. Deleted. |
| `user/views.py:143` `UpdateProfileView` | `get_object()` returns `self.request.user`. Attribute deleted. |
| `user/views.py:425` `NotificationListView` | Read by a scoped `get_queryset()`. Rewritten to name the model directly. |

The card/transaction IDORs the brief expected were genuinely fixed by the
2026-07-22 pass; `apps/payment/tests.py` still carries its regression tests
(`CardScopingTests`, `RetryPaymentScopingTests`). What that pass did *not* cover
was the token-binding path (H-1) or the field-level writes (M-1).

---

## Files changed

| File | Change |
|---|---|
| `apps/shared/permissions.py` | **C-1** — `UserRoles.STAFF` removed from `DASHBOARD_ROLES`, with the escalation documented inline. Only change; no class touched. |
| `apps/payment/serializers.py` | **H-1** — `card_token` write-only; reject a token bound to another user. **H-1/M-1** — `card_number`/`expiry_date`/`is_verified` read-only on `CardCreateSerializer`, `card_number`/`is_verified` read-only on `CardSerializer`. **M-2** — exception text logged, not returned. Module logger added. |
| `apps/payment/views.py` | **H-2** — `payment_card` / `payment_charge` throttle scopes on 7 views. **L-1** — `CardDetailView`/`CardRemoveView` given scoped `get_queryset()`; dead `queryset` attributes removed from 3 more. |
| `apps/user/views.py` | **H-2c** — `auth_register` / `token_refresh` throttle scopes. **L-1** — dead `queryset` attributes removed; `NotificationListView.get_queryset()` names the model directly. |
| `config/settings.py` | **H-2** — 4 new `DEFAULT_THROTTLE_RATES` entries. Required: `ScopedRateThrottle` raises `ImproperlyConfigured` for a scope with no rate, so this cannot be separated from the view annotations. No existing rate or setting altered. |
| `apps/payment/tests.py` | +9 tests: `CardTokenBindingTests`, `CardWriteProtectionTests`, `PaymentThrottleTests`. |
| `apps/user/tests.py` | +4 tests: `StaffRoleEscalationTests`. |
| `locale/{uz,ru,en,kk,ko}/LC_MESSAGES/django.po` | New msgid for the card-ownership refusal (×5); `"To'lov jarayonida xatolik yuz berdi: {}"` retired in favour of the placeholder-free form. Required by `apps/shared/tests/test_i18n_catalogs.py`. |

## Tests added

13 new tests, every one asserting **both** halves — the denial *and* that the
legitimate actor still gets through.

| Test class | Denial asserted | Positive half asserted |
|---|---|---|
| `StaffRoleEscalationTests` (4) | Customer-minted staff token → **403** on `/dashboard/users/`; staff phone → **400** at dashboard OTP login | `support_agent` still gets **200** on `/dashboard/users/`; `add-staff` still returns **201** and still creates a `staff` under `created_by` |
| `CardTokenBindingTests` (3) | Attacker posting the victim's token → **400**, Payme never called, no `Card` created, victim's row still unique | Owner saving their own token → **201**; and the 201 body contains no `card_token` anywhere |
| `CardWriteProtectionTests` (5) | `is_verified`/`card_number` PATCH ignored; other tenant gets **400** on GET *and* PATCH, with no PAN in the body | Owner renames their card → **200**; owner reads their card → **200** |
| `PaymentThrottleTests` (1) | 12 rapid calls to `payme/get-verify-token/` → a **429** appears | A **200** also appears — the limit does not break the normal caller |

**Verified these are real regression tests, not tests that pass by
construction.** Reverting each fix alone (`git stash push <file>`) and re-running:

- `apps/shared/permissions.py` reverted → 2 of 4 `StaffRoleEscalationTests` fail
  (`200 != 403` on `/dashboard/users/`, `200 != 400` on dashboard OTP login).
- `apps/payment/serializers.py` reverted → 4 of 8 card tests fail, including
  `AssertionError: Expected 'check_payme_card_token' to not have been called.
  Called 1 times.` and `is_verified` → `True is not false`.

## Test result

First green run after this workstream's changes, before other workstreams landed
further tests — 262 = the 249-test baseline + the 13 added here:

```
$ .venv/bin/python manage.py test apps --keepdb
Using existing test database for alias 'default'...
Found 262 test(s).
System check identified no issues (0 silenced).
..............................................................................
..............................................................................
..............................................................................
............................
----------------------------------------------------------------------
Ran 262 tests in 10.346s

OK
```

Final run at hand-off (the count has since moved as parallel workstreams landed
their own tests — this workstream added 13 and edited none):

```
$ .venv/bin/python manage.py test apps --keepdb
----------------------------------------------------------------------
Ran 272 tests in 11.385s

OK
```

Scoped run over the owned trees:

```
$ .venv/bin/python manage.py test apps.payment apps.user apps.shared --keepdb
Ran 166 tests in 5.026s

OK
```

> Note for the board: an intermediate full-suite run showed 1 failure in
> `apps.integration.tests.DeferredTaskDispatchTests` while WS-2 was mid-write
> (`apps/integration/views.py` → package). It cleared on its own and is not
> related to anything in this workstream — no file here touches broadcasts or
> Celery dispatch.

---

## Open items for a human

| # | Item | Why it needs you |
|---|---|---|
| 1 | **Audit production for `user_role='staff'` operators.** `SELECT id, username, phone_number, email, created_by_id FROM "user" WHERE user_role = 'staff' AND created_by_id IS NULL;` | C-1 takes console access away from every `staff` account. Any row with `created_by IS NULL` was not created by the customer-facing add-staff flow and may be a real internal operator — move them to `support_agent` before deploying, or they are locked out. Rows *with* a `created_by` are tenant employees and are meant to lose it. |
| 2 | **`ACCESS_TOKEN_LIFETIME = 7 days`.** | Deliberately not changed. An access token cannot be revoked; logout and role changes have a 7-day tail. Recommend 15–60 min. Needs a client-side impact call. |
| 3 | **Durable fix for card-token binding (H-1).** | The ownership check added here is a guard, not a boundary. The real fixes are (a) `unique=True` on `Card.card_token` — WS-7 owns migrations — and (b) not returning a raw token from `payme/get-verify-token/` at all: hold it server-side against the caller's session and have the client pass an opaque handle to `payme/verify-code/`. That is a redesign of the two-step card flow and needs product sign-off. |
| 4 | **`TransactionListView` inverted branch (L-2).** | The intended behaviour is almost certainly "an owner sees their employees' transactions too". Implementing that *widens* access across a tenant boundary, so it needs an explicit decision — not something an auditor should do unasked. |
| 5 | **Do tenant employees see anything?** | With `staff` out of `DASHBOARD_ROLES`, a `staff` account keeps only `IsAuthenticated` routes scoped to *itself* — which is empty, since the employer owns the assistants and cards. The add-staff feature may now be decorative. If employees are supposed to share their employer's resources, that is a scoping change in `apps/assistant/**` (WS-4), not a permission-class one. |
| 6 | **Throttle rates are a first guess.** | 10/min for card operations and 5/min for charges are chosen to be invisible to a real user while capping abuse. Tune against real traffic. They are also per-user (or per-IP when anonymous) — a distributed attacker with many accounts is not stopped by this alone. |
