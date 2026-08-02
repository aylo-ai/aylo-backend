# 2026-07-31 — Dashboard permission escalation via generic detail views

## Trigger

Asked to audit how permission checking works across the API and recommend the
right permission class per case. While mapping `apps/dashboard/views.py`
against `shared/permissions.py`, found that three generic
`RetrieveUpdateDestroyAPIView`s gate **every** HTTP method with the same
broad `IsDashboardUser` permission, even though sibling narrow-purpose
endpoints for the same resources correctly require `CanManageUsers` /
`CanManageFinance`. That means the narrow endpoints are security theater —
the same mutation is reachable through the generic view with a lower bar.

## How permissions work here (for reference)

- Every custom class in `shared/permissions.py` subclasses `IsAuthenticated`
  and layers a `request.user.user_role` check. DRF **ANDs** a
  `permission_classes` list, so composing e.g. `[IsAdmin, IsCustomer]` denies
  everyone — always pick the one class whose role set already covers what you
  want, never stack narrower classes hoping for OR semantics.
- `DASHBOARD_ROLES` (`super_admin, admin, manager, support_agent, staff`) is
  the floor for "can see the dashboard at all" — `IsDashboardUser`.
- `ADMIN_ROLES` (`super_admin, admin`) backs `IsAdmin`, `CanManageUsers`,
  `CanManageFinance` — money and account-identity actions.
- Role permission classes only answer "can this role call this view at all."
  They say nothing about *which object* — that's `get_queryset`/`get_object`
  filtering by owner, a separate axis. The `assistant` app does this
  correctly everywhere (`owned_assistants(request.user)` on every
  queryset/get_object), which is why it wasn't in scope here.
- **Recommended defaults per case**, using only classes that already exist:

  | Case | Class |
  |---|---|
  | Public, unauthenticated (webhooks, callbacks, landing lead capture) | `AllowAny` — but see `api-doctor`'s note: must still 4xx/5xx cleanly on junk input, never 500 |
  | Any authenticated user acting on their **own** resources | `IsAuthenticated` + queryset/`get_object` scoped to `request.user` (never rely on the permission class alone for tenancy) |
  | Any dashboard staff, read-only or low-stakes list/detail | `IsDashboardUser` |
  | Mutating a user's identity/role/active-state, or deleting a user | `CanManageUsers` |
  | Mutating billing/subscription/transaction state, refunds, cancellations | `CanManageFinance` |
  | Audit logs, system health, cross-tenant export/bulk actions | `IsAdmin` |
  | Super-admin-only operations | `IsSuperAdmin` |
  | **A `RetrieveUpdateDestroyAPIView` where GET should be broader than PUT/PATCH/DELETE** | override `get_permissions()` and branch on `self.request.method` — a single `permission_classes` list can't express this |

## Issue found and fixed

| Severity | Endpoint | Symptom | Root cause | Fix |
|---|---|---|---|---|
| **Critical** | `PATCH/PUT/DELETE /api/v1/dashboard/users/<pk>/` (`DashboardUserDetail`) | Any `support_agent`/`staff`/`manager` could PATCH `user_role` straight to `super_admin`, or DELETE any account — including admins — bypassing the `CanManageUsers`-gated change-role/toggle-active endpoints entirely. | `permission_classes = [IsDashboardUser]` applied uniformly; `DashboardUserSerializer` has `user_role`/`is_active` as writable fields with no extra guard in `update()`. | `apps/dashboard/views.py` — added `get_permissions()` requiring `CanManageUsers` on PUT/PATCH/DELETE; GET stays `IsDashboardUser`. |
| **High** | `PATCH/PUT/DELETE /api/v1/dashboard/subscriptions/<pk>/` (`DashboardSubscriptionDetail`) | Any dashboard role could rewrite `remained_request_count`, `end_date`, `pricing_package`, `auto_renew`, or delete the subscription outright — the same ground the `CanManageFinance`-gated cancel/extend endpoints cover. | Same pattern: `IsDashboardUser` on all methods. | Added `get_permissions()` requiring `CanManageFinance` on PUT/PATCH/DELETE. |
| **High** | `PATCH/PUT/DELETE /api/v1/dashboard/transactions/<pk>/` (`DashboardTransactionDetail`) | Any dashboard role could edit a transaction's `status`/`amount`/`refund_amount` or delete the record outright — no `AuditLog` call on this path either, unlike the User/Subscription detail views. | Same pattern: `IsDashboardUser` on all methods. | Added `get_permissions()` requiring `CanManageFinance` on PUT/PATCH/DELETE. |

Fix pattern applied to all three (`apps/dashboard/views.py`):

```python
def get_permissions(self):
    if self.request.method in ("PUT", "PATCH", "DELETE"):
        return [CanManageFinance()]  # or CanManageUsers()
    return super().get_permissions()
```

GET/list access is unchanged — still `IsDashboardUser` — since read access for
support staff is intentional and not the risk.

## Files changed

| File | Change |
|---|---|
| `apps/dashboard/views.py` | `get_permissions()` override on `DashboardUserDetail`, `DashboardSubscriptionDetail`, `DashboardTransactionDetail` to require `CanManageUsers`/`CanManageFinance` on write methods. |
| `apps/dashboard/tests.py` | Was an empty stub; added 12 regression tests across 3 classes proving support_agent gets 403 on write/delete but keeps read access, and admin still succeeds. |
| `docs/testing/ENDPOINT_TEST_CHECKLIST.md` | Marked the 3 fixed routes `written`, regenerated via the `endpoint-test-checklist` skill. |

## Tests added and result

`apps/dashboard/tests.py` — `DashboardUserDetailPermissionTests`,
`DashboardSubscriptionDetailPermissionTests`,
`DashboardTransactionDetailPermissionTests` (12 tests total). Verified each
fails against the pre-fix code (`git stash` on `views.py` alone) — 6 of the
12 failed with `200 != 403` on the exact assertions that matter, confirming
these are real regression tests, not tests that pass by construction.

```
.venv/bin/python manage.py test apps.dashboard.tests --keepdb
Ran 12 tests in 0.323s
OK
```

Full collateral-damage check across every app touching these permission
classes:

```
.venv/bin/python manage.py test apps.dashboard apps.payment apps.user apps.assistant apps.integration --keepdb
Ran 138 tests in 6.904s
OK
```

## Open items for a human decision

- **`DashboardTransactionDetail.update()`/`destroy()` write no `AuditLog`
  entry**, unlike the User and Subscription detail views on the same
  pattern. Not fixed here (out of scope for a permissions pass) but worth a
  follow-up — a financial record can currently be edited/deleted by an admin
  with zero audit trail.
- **`DashboardAssistantDetail`, `DashboardIntegrationDetail`,
  `DashboardConversationDetail`, `DashboardLeadDetail`** are the same
  generic-detail-view shape gated only by `IsDashboardUser` on all methods,
  but their resources (assistants, integrations, conversations, leads) are
  lower-stakes than identity/money — support staff editing/closing a
  conversation is arguably intended. Flagging in case product wants tighter
  scoping (e.g. `DashboardAssistantDetail.destroy()` behind `IsAdmin`, since
  `DashboardAssistantToggleActive` already is).
- The rest of `docs/testing/ENDPOINT_TEST_CHECKLIST.md` — 94 of 143 endpoints
  still show `none` for coverage. Dashboard alone accounts for most of it;
  recommend pointing the `test-writer` agent there next, one section at a
  time, with you checking off `Reviewed` as it lands.
