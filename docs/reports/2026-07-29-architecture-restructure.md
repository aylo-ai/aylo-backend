# Architecture restructure — Phase 0 (safety fixes)

**Date:** 2026-07-29
**Branch:** `dev`
**Status:** Phase 0 complete. Phases 1–4 pending.

Phase 0 of the restructure described in
`~/.claude/plans/look-over-this-project-proud-ladybug.md`. These are the fixes
that had to land before any structural move, so later phases build on a stable
base. No module was relocated in this phase.

---

## Issues found and fixed

### Critical

| # | Issue | Fix |
|---|---|---|
| 1 | **Live credentials committed to git** since `dfbb723`: `AMOCRM_SECRET_KEY`, `AMOCRM_ACCESS_TOKEN` (JWT valid to 2030), `BITRIX_CLIENT_KEY`, all as literals in `config/settings.py`. | `AMOCRM_CLIENT_ID`/`AMOCRM_SECRET_KEY`/`BASE_URL` now read from the environment, with an `ImproperlyConfigured` guard when `DEBUG` is off. `AMOCRM_ACCESS_TOKEN` and both `BITRIX_*` settings had **no reader anywhere in the tree** and were deleted rather than migrated. |
| 2 | **Broadcasts could silently never send.** `BroadcastListCreateView.create` saved the row then called `send_broadcast_task.delay(...)` inside the `ATOMIC_REQUESTS` transaction. The worker could look the broadcast up before commit; the task's `DoesNotExist` branch logs and returns, so the customer got a 201 and nothing went out. Same shape in `BillzSecretTokenHandlerView` (products never sync). | All 9 view-level dispatches now go through `transaction.on_commit(functools.partial(...))`. |
| 3 | **Duplicate module objects.** `sys.path.append(BASE_DIR/"apps")` plus bare `INSTALLED_APPS` entries made `shared.x` and `apps.shared.x` two distinct modules — two copies of `redis_client`, `conversation_service`, `instagram_service` and `agent`. | `sys.path` hack removed, `INSTALLED_APPS` fully qualified, ~113 imports and 9 test patch-target strings normalized to the `apps.` prefix. App labels are unchanged, so migrations, `db_table` names and content types are unaffected. |

### High

| # | Issue | Fix |
|---|---|---|
| 4 | **47 of 53 outbound `requests` calls had no `timeout`.** One unresponsive Meta/Telegram/amoCRM socket parks a gunicorn or Celery worker indefinitely. | New `apps/shared/http.py`: a shared `Session` that applies `DEFAULT_TIMEOUT = (5, 30)` whenever the caller omits one. All 47 call sites migrated across 13 modules. |
| 5 | **No index on the two hottest queries.** `Conversation` had no indexes at all despite `(assistant, user_id, token)` being filtered on every inbound message; `Integration.instagram_by_id` ORs across two unindexed columns on every webhook. | Three indexes added, built with `AddIndexConcurrently` (`atomic = False`) so the deploy does not lock tables the message pipeline writes to. |

### Incidental cleanups (CLAUDE.md §4)

- `Conversation.save()` was an override that only called `super()` — removed.
- `AMOCRM_ACCESS_TOKEN`, `BITRIX_CLIENT_ID`, `BITRIX_CLIENT_KEY` — dead settings, removed.

### Side effects worth noting

- `apps/shared/http.py` also enables connection pooling (`pool_maxsize=20`). The
  gateways hit a handful of hosts repeatedly, so this removes a TLS handshake per
  message. Retries are limited to connection failures and 5xx on idempotent
  methods — `urllib3`'s default `allowed_methods` excludes POST, so a message
  send is never duplicated.
- Migrating the `requests` call sites revealed that
  `test_get_user_info_returns_empty_dict_on_network_error` was making a **real
  network call** to the Instagram Graph API once its mock target no longer
  matched. The patch target was corrected; the test is offline again.

---

## Files changed

| File | Change |
|---|---|
| `config/settings.py` | Secrets → env + guard; `sys.path` hack removed; `INSTALLED_APPS` fully qualified |
| `.env.example` | **New** — documents every environment variable |
| `.gitignore` | `!.env.example` negation so the example is trackable under `.env*` |
| `apps/shared/http.py` | **New** — timeout-enforcing, pooled HTTP client |
| `apps/shared/addons/{telegram,instagram,payment,verification,billz}.py` | `requests.*` → `http.*` |
| `apps/shared/ai_service/{conversation,media,knowledge_base}.py` | `requests.*` → `http.*` |
| `apps/integration/views.py` | `requests.*` → `http.*`; 9 dispatches wrapped in `on_commit` |
| `apps/integration/{serializers,tasks/telegram,tasks/instagram_comments}.py` | `requests.*` → `http.*` |
| `apps/landing/views.py` | `requests.*` → `http.*` |
| `apps/assistant/models.py` | `Conversation` composite index; dead `save()` override removed |
| `apps/integration/models.py` | Instagram id columns indexed via `Meta.indexes` |
| `apps/assistant/migrations/0050_*`, `apps/integration/migrations/0043_*` | **New** — concurrent index builds |
| ~59 modules across `apps/` | Imports normalized to the `apps.` prefix |
| `CLAUDE.md` | §5 "Dual import paths" replaced with "One import path" — the old guidance is now wrong |

---

## Tests

| Test | Covers |
|---|---|
| `apps/shared/tests/test_http.py` (5) | Default timeout on every verb; explicit timeout not overridden; kwargs pass-through; POST never retried; reads never retried |
| `apps/shared/tests/test_import_paths.py` (3) | Bare paths unimportable; no duplicate module objects in `sys.modules`; singleton identity stable |
| `apps/integration/tests.py::DeferredTaskDispatchTests` (1) | **Regression for issue #2** — broadcast is not queued until commit, and the row exists by then |

`DeferredTaskDispatchTests` was verified to fail against the pre-fix code
(`AssertionError: Expected 'delay' to not have been called. Called 1 times.`)
before being accepted.

The pre-existing `TaskRegistrationTests` caught a genuine mistake mid-refactor:
an over-broad rewrite had stripped the `apps.` prefix from the Celery `name=`
strings, which would have stranded every queued task and broken the `celery.py`
queue routing. Restored and re-verified.

```
$ .venv/bin/python manage.py test apps.integration apps.assistant apps.shared \
      apps.payment apps.user --keepdb
Found 197 test(s).
System check identified no issues (0 silenced).
.....................................................................................................................................................................................................
----------------------------------------------------------------------
Ran 197 tests in 7.780s

OK
```

Baseline before this work was 188 tests passing; 9 added, 0 removed.

---

## Open items — need a human decision

| Item | Why it needs you |
|---|---|
| **Rotate the amoCRM credentials** (`AMOCRM_CLIENT_ID`, `AMOCRM_SECRET_KEY`) | The values remain in git history. Moving them to env makes them *replaceable*, not *safe* — only rotation in amoCRM does that. The working values were written to the gitignored `.env` so nothing breaks in the meantime. |
| `INSTAGRAM_APP_SECRET` / `INSTAGRAM_VERIFY_TOKEN` are absent from `.env` | The webhook fails closed without `APP_SECRET` and rejects every delivery. If production sets them another way this is fine; if not, Instagram is currently dark. Worth confirming. |
| Deploy ordering | The two index migrations use `atomic = False` + `CONCURRENTLY`. They must not run inside a wrapping transaction. If the deploy pipeline wraps `migrate`, that needs checking. |

## Next

Phase 1 breaks the `apps → shared → apps` dependency cycle by relocating the
seven `shared/` modules that import app models. Current baseline: **27**
function-local imports exist solely to dodge circular-import crashes; that number
is the progress metric for the phase.
