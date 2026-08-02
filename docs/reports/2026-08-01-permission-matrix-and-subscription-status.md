# 2026-08-01 — Endpoint permission matrix + subscription status messaging

## Trigger

Two asks: (1) a permission list per API endpoint, as a durable artifact, not
just a one-off answer; (2) when a user hasn't chosen a plan or their payment
hasn't gone through, the API must report the *correct* status rather than a
generic or misleading one.

## 1. Endpoint permission matrix

New: `docs/testing/ENDPOINT_PERMISSIONS.md`, generated (not hand-written) by
`.claude/skills/endpoint-test-checklist/scripts/permissions_matrix.py`, which
walks the live URL resolver — same technique as `api-doctor` and the existing
checklist script — and reads each view's real `permission_classes`. All 143
endpoints are covered, grouped by app, translated from raw class names into
plain-language access levels (Public → any authenticated → dashboard staff →
function-scoped admin → admin → super-admin).

Views whose `get_permissions()` is overridden (11 of them) can't be read by
introspection alone — their effective per-method behavior is hand-maintained
in `OVERRIDE_NOTES` inside the script; keep that in sync when those views
change. The `endpoint-test-checklist` skill (from the previous session) now
documents both scripts.

Auditing the matrix surfaced nothing new beyond the three dashboard views
already fixed on 2026-07-31 (see that report) — everything else checked out:
customer-owned resources use `IsAuthenticated` + queryset ownership scoping,
money/identity actions use `CanManageFinance`/`CanManageUsers`, and the four
GET-public/POST-admin views (`Feature`, `PricingPackage`, `PrivacyPolicy`,
`UserAgreement` list-create) split correctly via `get_permissions()`.

## 2. Subscription status messaging

### Bug: cancelled subscriptions weren't blocked

`SubscriptionValidationMixin.validate_subscription()` (`apps/shared/mixins.py`)
only ever checked `status == INACTIVE`. `DashboardSubscriptionCancel` sets
`CANCELLED`, not `INACTIVE` — so an admin-cancelled subscription with
remaining tokens and a still-future `next_payment_date` sailed through every
check and kept working. This gates assistant/conversation/message/integration
creation and file uploads (`apps/assistant/serializers.py`,
`apps/integration/serializers.py`), so a cancelled customer could keep using
the product.

### Bug: wrong message on inactive-but-full-tokens subscriptions

Check order was: no-subscription → tokens-exhausted → not-active → expired.
A subscription selected but never paid for starts with a **full** token
count (`SubscriptionCreateView.create()`) and `status = INACTIVE` — so it
skipped the tokens check and hit "obunangiz faol emas" (subscription not
active), a correct-enough but non-specific message. Reordering to check
status first, and splitting "never paid" from "was active and lapsed" using
`last_payment_date` (only ever set by a successful payment — Payme, manual
payment, or billing renewal), gives three distinct, accurate messages instead
of one overloaded one.

### Fix (`apps/shared/mixins.py`)

New order and branching:

1. No subscription → "tanlang" (choose a plan)
2. `status == CANCELLED` → "bekor qilingan" (you cancelled)
3. `status != ACTIVE` (blocklist → allowlist, future-proof) and
   `last_payment_date is None` → "to'lov hali amalga oshirilmagan" (payment
   not yet processed)
4. `status != ACTIVE` and previously paid → "obunangiz faol emas" (not
   active — lapsed/deactivated after having worked before)
5. `remained_request_count <= 0` → tokens exhausted
6. `next_payment_date` in the past → expired (cleaned up the inline ternary
   into a plain `and`)

### Related fix: self-service cancel set the wrong status

`SubscriptionCancellationView` (`apps/payment/views.py`) set `INACTIVE` on
cancel, while the dashboard's admin cancel sets `CANCELLED`. That meant a
self-cancelled customer got the generic "not active" message instead of the
accurate "you cancelled" one, and — before the fix above — wasn't reliably
blocked either. Changed to set `CANCELLED`, matching `DashboardSubscriptionCancel`.

### i18n

Two new source strings needed catalog entries per `CLAUDE.md` §5 (enforced by
`apps/shared/tests/test_i18n_catalogs.py`). Delegated to the `i18n-translator`
agent: added to all five locales (`en`, `ru`, `uz`, `kk`, `ko`), fixed stale
line-number comments the edit shifted, and added
`SubscriptionStatusMessageTests` (3 tests) asserting all five subscription
messages exist per language, no catalog echoes the Uzbek source, and the five
causes render as five distinct strings — the direct regression guard, since
showing the same text for "cancelled" and "not active" routes the user to the
wrong screen regardless of which branch fired.

### Checklist-generator fix

While verifying the new `subscriptions/cancel/` test showed up in
`docs/testing/ENDPOINT_TEST_CHECKLIST.md`, found the regenerate script froze
*every* prior Coverage cell, not just human-reviewed or agent-`written` ones —
so a "none"/heuristic guess never refreshed on later runs even after real
tests landed. Fixed: only `written (...)` or a checked `[x]` Reviewed row is
now frozen across regenerations; everything else is recomputed fresh every
time, which is the whole point of a "heuristic" label.

## Files changed

| File | Change |
|---|---|
| `.claude/skills/endpoint-test-checklist/scripts/permissions_matrix.py` | New — generates the permission matrix. |
| `.claude/skills/endpoint-test-checklist/scripts/regenerate.py` | Fixed stale-freeze bug in Coverage recomputation. |
| `.claude/skills/endpoint-test-checklist/SKILL.md` | Documents the new script and the access-level ladder. |
| `docs/testing/ENDPOINT_PERMISSIONS.md` | New — generated permission matrix, 143 rows. |
| `docs/testing/ENDPOINT_TEST_CHECKLIST.md` | Regenerated — 58/143 now show coverage (was 49; picked up tests this session and previously-missed heuristic matches). |
| `apps/shared/mixins.py` | `validate_subscription()` — block `CANCELLED`, reorder checks, split "never paid" vs "lapsed" messaging. |
| `apps/shared/tests/test_subscription_validation_mixin.py` | New — 8 tests covering every branch. |
| `apps/payment/views.py` | `SubscriptionCancellationView` sets `CANCELLED`, not `INACTIVE`. |
| `apps/payment/tests.py` | New `SubscriptionCancellationTests` (2 tests). |
| `locale/{en,ru,uz,kk,ko}/LC_MESSAGES/django.po` | +2 msgid/msgstr pairs each (via `i18n-translator` agent). |
| `apps/shared/tests/test_i18n_catalogs.py` | +`SubscriptionStatusMessageTests` (3 tests, via `i18n-translator` agent). |

## Tests added and result

```
.venv/bin/python manage.py test apps.shared apps.assistant apps.integration apps.payment apps.dashboard apps.user apps.blog apps.landing --keepdb
Ran 249 tests in 13.056s
FAILED (failures=2)
```

The 2 failures are `apps.shared.tests.test_deployment_compose.DozzleHardeningTests`
— pre-existing, unrelated to this change (Dozzle/docker-compose config drift
from an earlier commit). Verified independently twice (by me and by the
`i18n-translator` agent) via `git stash` on the touched files: both fail
identically on a clean checkout. Every test I added or modified passes; 247/249
overall.

## Open items for a human decision

- **Dozzle deployment-compose failures** (pre-existing, not touched here) —
  `apps/shared/tests/test_deployment_compose.py` expects
  `com.docker.compose.project=repliuz` and no `EVENTS` env var on the socket
  proxy; current `docker-compose` config has `aylochat` and an extra `EVENTS`.
  Needs someone who knows which is the intended current state to fix the
  test or the compose file.
- **`msgfmt`/`compilemessages` validation** — the i18n agent couldn't run the
  real GNU `msgfmt` on this host (no root) and used an equivalent Python
  implementation instead. `deployment/start.sh` runs real `compilemessages`
  before gunicorn starts, so worth a real `msgfmt -c` pass in CI/the Docker
  build before this ships.
- **kk translation confidence** — "тоқтатылды" ("was stopped/terminated") for
  "cancelled" vs the alternative "бас тартылды" ("was declined"); flagged by
  the i18n agent as its least-confident pick, worth a native-speaker check.
- **`apps/payment/management/commands/seed_pricing_packages.py`** has an
  unrelated uncommitted change already sitting in the working tree before
  this session touched anything (new pricing copy/features, price changes on
  Basic/Pro). Left untouched — it's your in-progress work, not part of this
  change; flagging so it doesn't get lost or accidentally swept into a commit
  with this branch's unrelated diffs.
- Endpoint checklist still shows 85/143 with no coverage — dashboard remains
  the largest gap. Recommend pointing `test-writer` there next.
