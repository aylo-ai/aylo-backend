# Backend hardening & quality work board — 2026-08-01

Scope agreed with the owner: **no new features.** Security, readability/structure, and
query efficiency on code that already exists. API contracts stay identical unless a
contract change *is* the security fix.

## 1. Survey (measured, not estimated)

| Metric | Value |
|---|---|
| Test suite baseline | 249 tests, **green** (2 stale deployment-compose assertions fixed first — see WS-0) |
| Largest modules | `dashboard/views.py` 1707 · `integration/views.py` 1632 · `dashboard/serializers.py` 939 |
| View classes in those two files | ~50 (dashboard) · ~33 (integration) |
| `queryset = X.objects.all()` at class level | **68 across 6 apps** — every detail/update/destroy route among them is an IDOR candidate |
| `select_related` / `prefetch_related` in the whole tree | **18** — far below one per list endpoint |
| `SerializerMethodField` in `dashboard/serializers.py` | **42**, many doing `obj.x.count()` → one query per row per field |
| `AllowAny` surfaces | 16, incl. amoCRM OAuth handler, Instagram/Telegram webhooks, payment callbacks |
| Throttled endpoints | 4 (otp_send, otp_verify, dashboard login, landing_lead) |
| Raw SQL / `eval` / `.extra()` | none — good |

### Already done before this board (not re-litigated)
`docs/reports/2026-07-31-dashboard-permission-escalation.md` and
`2026-08-01-permission-matrix-and-subscription-status.md` scoped much of the dashboard
app. Dashboard therefore enters this board as an **optimization** target, not a
security one.

## 2. Workstreams

| ID | Discipline | Scope (exact paths — sole owner) | Agent | Depends on | Risk |
|---|---|---|---|---|---|
| WS-0 | Baseline | `apps/shared/tests/test_deployment_compose.py` | (done inline) | — | none |
| WS-1 | Readability / structure | `apps/dashboard/views.py`, `apps/dashboard/serializers.py` → packages | code-structurer | WS-0 | med — biggest file, many callers |
| WS-2 | Readability / structure | `apps/integration/views.py` → package | code-structurer | WS-0 | med — webhook routes must not move URL-wise |
| WS-3 | Security | `apps/payment/**`, `apps/user/**` | security-auditor | WS-0 | high value — money + auth |
| WS-4 | Security | `apps/integration/**`, `apps/assistant/**` | security-auditor | WS-2 | high — IDOR + webhook auth |
| WS-5 | Optimization | `apps/dashboard/**` (N+1, annotate) | query-optimizer | WS-1 | med — 42 method fields |
| WS-6 | Optimization | `apps/assistant/**`, `apps/integration/**` querysets | query-optimizer | WS-4 | med |
| WS-7 | Optimization | `models.py` indexes across apps + migrations | query-optimizer | WS-5, WS-6 | migrations serialize |
| WS-8 | Coverage | test sweep + `docs/testing/ENDPOINT_TEST_CHECKLIST.md` | test-writer | all | — |

## 3. File-ownership map

One workstream owns a file at a time. This is what stops two agents colliding.

| File / tree | Owner |
|---|---|
| `apps/dashboard/views.py`, `apps/dashboard/serializers.py` | WS-1, then WS-5 |
| `apps/integration/views.py` | WS-2, then WS-4, then WS-6 |
| `apps/payment/**`, `apps/user/**` | WS-3 |
| `apps/assistant/**` | WS-4, then WS-6 |
| `apps/*/models.py` + migrations | WS-7 only |
| `apps/shared/mixins.py`, `permissions.py` | WS-3 first; later streams extend, never rewrite |
| `config/settings.py` | WS-3 (review only) |

## 4. Waves

- **Wave 1 (parallel):** WS-1, WS-2, WS-3 — disjoint trees.
- **Wave 2 (parallel):** WS-4, WS-5 — operate on the structures wave 1 produced.
- **Wave 3:** WS-6, then WS-7 alone (migrations).
- **Wave 4:** WS-8.

## 5. Definition of done — every workstream

1. Root-cause fix, no feature added, no response body changed.
2. Tests: security → assert denial **and** that the legitimate owner still passes;
   optimization → `assertNumQueries` before/after with a ≥5-row fixture; structure →
   the *unedited* existing suite passes.
3. `.venv/bin/python manage.py test <app> --keepdb` green, output pasted.
4. Own report in `docs/reports/`, per CLAUDE.md §6.

## 6. Open items for a human

| Item | Why it needs you |
|---|---|
| Uncommitted work in tree at board creation | `dashboard`, `payment`, `shared`, locale files were already modified. A checkpoint commit before wave 1 would make rollback trivial. Not done — CLAUDE.md §7 says commit only when asked. |
| Role breadth ambiguity | Where a staff/admin role's intended reach is unclear, agents implement the restrictive reading and list it. Review those lists. |
| Index migrations on hot tables | May need `CREATE INDEX CONCURRENTLY` at deploy rather than a blocking migration. |
