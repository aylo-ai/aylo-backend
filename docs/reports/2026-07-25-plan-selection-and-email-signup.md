# Plan selection after sign-up, and email sign-up hardening

**Date:** 2026-07-25
**Driver:** the `aylo-frontend` sign-up flow needs a "choose your plan" step
directly after registration, and email (as opposed to SMS) sign-up needed to be
verified end to end.

Nothing was missing from the API for either feature — `POST
payment/subscriptions/create/` and the email branch of `auth/send-otp/` +
`auth/verify-otp/` both already existed. What this change does is make them
correct, testable offline, and usable from a fresh database.

---

## 1. Issues found and fixed

| # | Severity | Area | Issue | Fix |
|---|---|---|---|---|
| 1 | High | `PricingPackageSerializer.validate` | Indexed `attrs["price"]` / `attrs["discount_price"]` directly. Both fields are optional on the model and a PATCH only carries changed fields, so **any payload omitting either one raised `KeyError` → HTTP 500**. | Read through to `self.instance` with `attrs.get(...)` and skip the check when a value is genuinely absent. |
| 2 | High | `PricingPackageSerializer.validate` | The discount check was inverted: `if discount_price < price: raise("discount cannot be lower than price")`. This **rejected every legitimate discount** and accepted nonsensical ones above list price. | Reject `discount_price > price` (and negatives), with a corrected message. |
| 3 | Medium | `PricingPackageRetrieveView.update`, `FeatureRetrieveView.update` | The overridden `update()` dropped DRF's `partial` kwarg, so **every PATCH behaved as a PUT** and demanded the full object. | Pass `partial=kwargs.pop("partial", False)` through to the serializer. |
| 4 | Medium | `shared/addons/verification.send_email_code` | The `except` returned `str(e)` to the API caller, **leaking SMTP host/credential detail** from a delivery failure into an unauthenticated endpoint's response. | Log the exception with `logger.exception`; return a generic message. Same treatment for `verify_email_code`. |
| 5 | Medium | `send_email_code` | The code was written to Redis *before* the mail was sent. A failed send therefore **replaced a code the user was still holding** with one they never received. | Send first, store only on success. |
| 6 | Low | `SubscriptionSerializer` | Declared `user = UserSerializer(read_only=True)`, but `Subscription` has no `.user` attribute (the FK lives on `User` with `related_name="users"`). DRF silently raised `SkipField`, so the field never rendered — dead code that implied an API contract that did not exist. | Removed. |
| 7 | Low | `SubscriptionSerializer` | `pricing_package` is write-only (a bare UUID in, nothing out), so the create response never named the plan that had just been bought — the client needed a second round-trip to the profile endpoint. | Added `to_representation` that echoes the resolved `PricingPackageSerializer` payload. |
| 8 | Low | `payment/urls.py` | Commented-out route referencing `views.SubscriptionRetrieveView`, a view that does not exist. | Deleted (§4 of CLAUDE.md). |
| 9 | Low | `config/settings.py` | `EMAIL_BACKEND` was hardcoded to SMTP, so the email sign-up path could not be exercised locally without live Zoho credentials. | Now `os.environ.get("EMAIL_BACKEND", <smtp default>)`. Production behaviour is unchanged. |

### Also cleaned up while in the file

- `verification.py`: hoisted the function-local `render_to_string` import to the
  module top, replaced the hardcoded `'year': 2024` template context with the
  current year, introduced `EMAIL_CODE_TTL` instead of the repeated literal
  `300`, and corrected a comment that claimed a 300-second TTL was "1 hour".

---

## 2. New: `seed_pricing_packages` management command

`subscriptions/create/` only accepts an existing, active `PricingPackage`, so a
fresh database has nothing for the sign-up flow's plan step to offer — the
development database held exactly one package, unnamed, priced 0.

```bash
.venv/bin/python manage.py seed_pricing_packages
```

Creates or updates the standard **Free / Basic / Pro** ladder plus the eight
`Feature` rows they reference. Idempotent (matches on package name), so it is
safe to re-run after changing a price or a limit.

---

## 3. Behaviour confirmed against the running server

`subscriptions/create/` was exercised live before and after the changes:

| Case | Result |
|---|---|
| Free package (`price == 0`) | `status: "active"`, `next_payment_date: null`, `auto_renew: false` — usable immediately |
| Paid package (`price > 0`) | `status: "inactive"`, `next_payment_date` set, `auto_renew: true` — **needs a Payme payment to activate** |
| Second plan while one is *active* | 400 `"Sizda allaqachon faol obuna mavjud."` |
| Second plan while the existing one is *inactive* | Allowed — an unpaid plan can be swapped, so a user who never pays is not trapped |
| Unknown package UUID | 400 `"Narx paketi topilmadi."` |
| Retired (`is_active=False`) package | 400 |
| Unauthenticated | 401 |

The paid-plan result is the important one for the frontend: **choosing a paid
plan does not grant access.** The plan-selection screen surfaces that honestly
rather than implying the subscription is live.

---

## 4. Files changed

| File | Change |
|---|---|
| `config/settings.py` | `EMAIL_BACKEND` made env-overridable |
| `apps/shared/addons/verification.py` | Email OTP: send-before-store, no exception leak, TTL constant, import/comment cleanup |
| `apps/payment/serializers.py` | `PricingPackageSerializer.validate` rewritten; `SubscriptionSerializer` dead `user` field removed, `to_representation` added |
| `apps/payment/views.py` | `partial` kwarg honoured in `FeatureRetrieveView.update` and `PricingPackageRetrieveView.update` |
| `apps/payment/urls.py` | Dead commented route removed |
| `apps/payment/management/commands/seed_pricing_packages.py` | **New** — Free/Basic/Pro seeder |
| `apps/user/tests.py` | **New tests** — email OTP delivery + email sign-up flow |
| `apps/payment/tests.py` | **New tests** — plan selection + pricing-package validation regressions |

---

## 5. Tests

New coverage (all offline — Redis, SMTP and the SMS provider are faked):

**`apps/user/tests.py`**
- `EmailCodeDeliveryTests` — the emailed code is the one the cache accepts; a
  failed send stores nothing and leaks no SMTP detail (regression for #4/#5);
  a correct code verifies once and is burned; the attempt cap discards the code.
- `EmailSignUpFlowTests` — `send-otp` accepts an email and rejects a malformed
  one; verifying creates the account exactly once with `auth_type="email"`; a
  wrong code creates no account; a brand-new account has no name and no
  subscription (what the frontend's two onboarding gates key off).

**`apps/payment/tests.py`**
- `PlanSelectionTests` — the eight rows in §3 above.
- `PricingPackageValidationTests` — regressions for #1, #2 and #3.

```
$ .venv/bin/python manage.py test --keepdb
Found 145 test(s).
System check identified no issues (0 silenced).
.................................................................................................................................................
----------------------------------------------------------------------
Ran 145 tests in 7.458s

OK
```

---

## 6. Open items for a human

1. **Paid plans cannot actually be paid for.** `payme/card/add/` +
   `payme/card/pay-subscription/` need Payme merchant credentials and
   verification, so a paid subscription stays `inactive` indefinitely. Until
   that is wired, the only self-service path to an active subscription is a
   free package. The frontend says so explicitly instead of faking it.
2. **Switching an active plan is impossible.** `SubscriptionSerializer.validate`
   rejects a new subscription while one is active, and the only way out is
   `subscriptions/cancel/` (which requires a reason and leaves the account with
   no plan). If self-service upgrades are wanted, the create path needs to
   handle "replace the current plan" explicitly.
3. **Orphaned subscription rows.** Choosing a different plan while the current
   one is inactive re-points `User.subscription` and leaves the old
   `Subscription` row behind with nothing referencing it. Harmless today, worth
   a cleanup task if these accumulate.
4. **One unnamed package** (`name=""`, 100 000 requests, 1 000 days) exists in
   the development database and shows up in the public list. It looks like a
   leftover; the frontend renders a fallback title for it, but someone should
   decide whether to name or retire it.
