# Pricing ladder rework: 989,000 popular tier + custom "for companies" tier

**Date:** 2026-08-17
**Branch:** `feat/pricing-custom-tier` (based on `origin/dev` @ `7a28729`)

## What was asked

Make the popular package cost **989,000 UZS for 5,000 conversations**, and make
the last package a **custom tier for companies**. Two decisions were confirmed
before implementing:

| Decision | Choice |
|---|---|
| Ladder shape | Three tiers: Free → Pro (989k) → Korporativ (custom) |
| What the custom tier does | Not purchasable self-service; it collects a contact-sales request |

## The ladder now

| Tier | `type` | Price | Conversations | Popular | Buyable self-service |
|---|---|---|---|---|---|
| Free | `free` | 0 | 100 | no | yes |
| Pro | `pro` | 989,000 UZS | 5,000 | **yes** | yes |
| Korporativ | `custom` | — (negotiated) | agreed per company | no | **no — quote request** |

`Basic` (299,000) leaves the ladder. The seed command **deactivates** it rather
than deleting it: existing subscriptions still point at that row, and
`Subscription.pricing_package` is the only record of what a customer bought.

## Changes

### 1. The custom tier is a first-class concept

`PricingPackageType.CUSTOM` now means "priced per company" (it was previously
being used for the `Basic` tier, which was just a normal paid plan).
`PricingPackage.is_custom` derives from it — no new column.

Because a custom package has no chargeable amount, both self-service money
paths refuse it:

| Path | Behaviour |
|---|---|
| `POST /payment/subscriptions/create/` | 400 — "ariza qoldiring, savdo bo'limi bog'lanadi" |
| `POST /payment/payme/card/update-subscription/` | 400, **before** any Payme receipt is created |

Without this, a user could create a subscription that nothing can ever charge
(amount 0 on the receipt), or an upgrade that silently gave away the top tier.

### 2. Contact-sales request

`POST /api/v1/payment/pricing-packages/<uuid:pk>/request/` — public
(`AllowAny`), throttled on the `landing_lead` scope. The pricing page is public
and most companies filling this in have no account yet; when a token *is*
present the account is attached to the row.

Stores a `CustomPackageRequest` (company, contact name, phone, email, expected
conversations, comment) and announces it in the verified Telegram sales groups.
Returns 400 if the package is not a custom one, so the form cannot be used as a
generic lead sink on a priced tier.

Every field is HTML-escaped before it reaches Telegram — `parse_mode` is HTML
and all of it is free text from a public form. This mirrors the fix already
applied to the landing lead form, and is covered by its own test.

### 3. Pricing list is ordered as a ladder

The list endpoint inherited the model's `-created_time` ordering, so the
pricing page led with whichever package was seeded last (in practice:
Korporativ first). It now returns cheapest-first with the custom tier pinned
last, via a `Case`/`When` annotation on `type`.

### 4. Serializer exposes only the derived flag

`PricingPackageSerializer` gains `is_custom` so the frontend can render a
"contact us" call to action instead of a price on the last card.

The raw `type` enum is **not** exposed: `PublicCatalogueTests` deliberately
pins the public payload to what the pricing page needs, and the internal plan
classification is not part of that. The dashboard serializer still returns
`type` for admins.

### 5. Shared Telegram send loop

The landing lead form and this new quote request post into the same sales
groups. The send loop moved to `apps/landing/notifications.py` so there is one
place that talks to Telegram — the escaping fix upstream applied to the lead
form had to be reproduced for the quote request, and duplicating the loop is
how that kind of fix goes missing in one of the two copies.

`LandingLeadCreateTests` patches the send target, so its two patch targets moved
with the code.

### 6. Cleanups made along the way

- `apps/landing/serializers.py` — the phone-number error was the only
  user-facing string in the app not wrapped in `_()`; now wrapped and
  translated.
- Blog seed price claims ("299,000 so'mdan boshlanadi", RU and EN variants)
  synced to 989,000 — the seed command's own comment asks for these to be kept
  in step.
- Five new msgids translated in all five catalogs (uz/ru/en/kk/ko).

### 7. Merge conflict markers resolved in `apps/payment/tests.py`

`origin/dev` carries **committed, unresolved conflict markers** in this file
(from `473f4c3`, via the commit named "feat: merge conflict error happened").
The file does not parse, so the payment suite could not run at all.

The two sides are disjoint and additive — `CardTokenBindingTests` /
`CardWriteProtectionTests` / `PaymentThrottleTests` on one side,
`PublicCatalogueTests` / `PaymeVerificationThrottleTests` on the other — so the
resolution keeps both and drops only the three marker lines. Nothing else in
the file was rewritten.

**Two more files on `origin/dev` are still broken and were left alone** — see
open items.

## Files changed

| File | Change |
|---|---|
| `apps/payment/models.py` | `PricingPackage.is_custom` property; new `CustomPackageRequest` model |
| `apps/payment/migrations/0023_custompackagerequest.py` | New (create model) |
| `apps/payment/serializers.py` | `is_custom` exposed; custom tier rejected in subscribe + upgrade; `CustomPackageRequestSerializer` |
| `apps/payment/views.py` | `CustomPackageRequestCreateView`; ladder ordering on the list endpoint |
| `apps/payment/urls.py` | `pricing-packages/<uuid:pk>/request/` |
| `apps/payment/admin.py` | `CustomPackageRequest` admin; package list shows `type`/`is_popular`/`is_active` |
| `apps/payment/services/notifications.py` | New — sales alert for a quote request, escaped and fail-soft |
| `apps/payment/management/commands/seed_pricing_packages.py` | Free / Pro (989k, 5000) / Korporativ; retires `Basic` |
| `apps/payment/tests.py` | Conflict resolved; new `CustomPackageTests`; fixtures retyped `CUSTOM` → `PRO`; payload contract test updated |
| `apps/landing/notifications.py` | New — shared Telegram fan-out |
| `apps/landing/views.py` | Uses it instead of its own send loop |
| `apps/landing/serializers.py` | Phone-number message wrapped in `_()` |
| `apps/landing/tests.py` | Patch targets follow the moved send loop |
| `apps/blog/management/commands/seed_blog_posts.py` | Price claims 299,000 → 989,000 (uz/ru/en) |
| `locale/*/LC_MESSAGES/django.po` | 5 new msgids × 5 languages |
| `docs/testing/ENDPOINT_*.md` | Regenerated for the new route |

## Tests

New `CustomPackageTests` (10 cases):

| Test | Proves |
|---|---|
| `test_the_list_marks_the_custom_tier` | `is_custom` reaches the pricing page |
| `test_the_list_comes_back_as_a_ladder` | Free → Pro → Korporativ order |
| `test_the_popular_tier_carries_its_price_and_conversation_limit` | 989,000 / 5,000 / popular |
| `test_the_custom_tier_cannot_be_subscribed_to` | 400, no subscription created |
| `test_the_custom_tier_cannot_be_upgraded_to` | 400 **and** no Payme receipt attempted |
| `test_a_company_can_request_a_quote` | Row stored, package + user linked, phone normalised |
| `test_an_anonymous_visitor_can_request_a_quote` | Works with no token, `user` is null |
| `test_a_short_phone_number_is_rejected` | 400, nothing stored |
| `test_a_priced_package_has_no_quote_form` | Quote form refused on a priced tier |
| `test_a_failing_sales_notification_does_not_lose_the_request` | Telegram outage still returns 201 |
| `test_the_sales_alert_escapes_attacker_markup` | `<a href=…>` in a company name cannot forge markup in the sales group |

```
$ .venv/bin/python manage.py test apps.payment.tests.CustomPackageTests \
      apps.payment.tests.PlanSelectionTests \
      apps.payment.tests.PublicCatalogueTests apps.landing --keepdb
Ran 45 tests in 0.408s
OK
```

Wider run:

```
$ .venv/bin/python manage.py test apps.payment apps.landing \
      apps.shared.tests.test_i18n_catalogs --keepdb
Ran 92 tests in 1.157s
FAILED (failures=2, errors=6)
```

**All 8 are pre-existing on `origin/dev` and none are caused by this branch.**
Verified by stripping the conflict markers on a pristine `origin/dev` worktree
and running the same tests there:

| Failure | Cause |
|---|---|
| `CardTokenBindingTests` ×3 | Pre-existing on `origin/dev` |
| `PaymeVerificationThrottleTests` ×2 | Pre-existing on `origin/dev` |
| `SourceStringTests` ×3 | `apps/integration/tests.py` on `origin/dev` does not parse |

## Open items for a human

1. **`origin/dev` has two more broken files.** `apps/integration/tests.py` is
   truncated mid-statement (around line 1646) and
   `apps/shared/tests/test_deployment_compose.py` has committed conflict
   markers. Neither is in this MR's scope, but until they are fixed the i18n
   source-string tests cannot run — they parse every file in `apps/`. The same
   botched merge is the likely cause as in `apps/payment/tests.py`.
2. **Five payment tests already fail on `origin/dev`** (`CardTokenBindingTests`,
   `PaymeVerificationThrottleTests`) — unrelated to pricing, but worth a look
   before the next release.
3. **Conversation limit for a custom subscription.** `Korporativ` is seeded
   with `request_count = 0`. When sales closes a deal, an admin has to set the
   agreed conversation count on the subscription (or create a per-company
   package) — otherwise the account has zero conversations. There is no
   automated path from an accepted quote to an active subscription; that was
   out of scope.
4. **`Basic` subscribers.** Existing `Basic` subscriptions keep running until
   they lapse. Nobody has told them the tier is retired.
5. **Blog price claims.** Updated in the seed command, but any post already
   written to the production database still says 299,000 — re-run
   `seed_blog_posts` or edit those posts.
