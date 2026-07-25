# Change Report — C1: `Message.save()` quota crash & race

**Date:** 2026-07-21
**Branch:** `ai-pipeline-response`
**Scope:** Step 1 of the assistant-app investigation
(`docs/reports/2026-07-21-assistant-app-investigation.md`).
**Test status:** ✅ 97/97 passing (`apps.assistant`, `apps.integration.tests`,
`apps.shared.ai_service.tests`, `apps.user.tests`).

## Problem
`Message.save()` (`apps/assistant/models.py`) charged the owner's request quota
inline on every assistant reply, with three defects:

1. **Crash:** `subscription = assistant_user.subscription` can be `None`
   (nullable FK); `subscription.remained_request_count` then raised
   `AttributeError` — failing the save and the whole turn for any assistant whose
   owner had no subscription.
2. **Lost update:** `remained_request_count -= 1` is a read-modify-write, so two
   concurrent replies could both read the same value and only decrement once.
3. **Write amplification / double-charge risk:** it re-saved the conversation via
   `conversation.save()` and charged on *every* save — including later updates to
   the same message.

## Fix
| File | Change |
|---|---|
| `apps/assistant/models.py` | Rewrote `Message.save()`; added `_charge_owner_subscription()` |
| `apps/assistant/tests.py` | Added `MessageQuotaTests` (6 tests) |

- **No crash:** a missing subscription is now a guarded no-op.
- **Atomic decrement:** quota is decremented with a single
  `Subscription.objects.filter(pk=..., remained_request_count__gt=0).update(remained_request_count=F(...) - 1)`
  — race-free and never negative.
- **Charge once, on creation only:** guarded by `self._state.adding` and
  `sender == ASSISTANT`, so message edits don't re-charge.
- **Lighter write:** conversation activity time is bumped with one
  `Conversation.objects.filter(pk=...).update(updated_time=now())` instead of a
  full model save.
- **Notify on real consumption:** the low-token warning fires only when a request
  was actually charged and the balance hits 0/10/20.
- Removed the now-unused `transaction` import (CLAUDE.md §4).

## Tests added (`MessageQuotaTests`)
No-subscription reply doesn't crash · assistant reply charges exactly one · user
message doesn't charge · editing a reply doesn't re-charge · quota never goes
negative · hitting the threshold notifies the owner.

## Not in this step (tracked in the investigation report)
C2 (IDOR/tenant scoping), C3 (`AllowAny` messages), C4 (model-mismatched views),
C5 (lead-export files), H1–H3, the N+1 / index optimizations, and the dead-code
sweep remain open — proposed as the next steps.

---

## 2026-07-22 update — fix actually applied

The model change described above was missing from the tree (only the
`MessageQuotaTests` had survived), so the two regression tests failed. The fix
was (re)implemented today in `apps/assistant/models.py` `Message.save()` exactly
as designed here: `None`-guarded subscription, `self._state.adding` charge-once
guard, race-free `filter(remained_request_count__gt=0).update(F(...) - 1)`
decrement, single-UPDATE conversation bump, notify only on real consumption,
and the unused `transaction` import removed.

**Test status:** ✅ 103/103 passing (full `apps` suite, `--keepdb`).
