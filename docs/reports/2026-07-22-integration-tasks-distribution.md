# 2026-07-22 — Integration tasks distribution (tasks.py split)

`apps/integration/tasks.py` (943 lines) mixed Celery tasks, plain helpers, and inlined
vendor HTTP clients. It is now a domain-split `tasks/` package with vendor clients
extracted to `apps/shared/addons/`, following the existing `telegram.py`/`instagram.py`
addon convention.

## Task-vs-function verdict

Every call site in the repo was mapped before deciding. Result: the classification was
already correct — no task needed demoting, no helper needed promoting — except one dead task.

| Symbol | Verdict | New home |
|---|---|---|
| `process_message_task`, `process_voice_task`, `process_photo_task` | task ✅ | `tasks/telegram.py` |
| `process_instagram_message`, `process_shared_post_message` | task ✅ | `tasks/instagram_messaging.py` |
| `process_instagram_comment`, `process_instagram_comment_message` | task ✅ | `tasks/instagram_comments.py` |
| `handle_postback_event_task`, `send_step_message_task` | task ✅ | `tasks/instagram_flows.py` |
| `process_collected_messages` (+ `WAIT_SECONDS`) | task ✅ (debounce) | `tasks/collector.py` |
| `send_broadcast_task`, `send_message_integration_task` | task ✅ | `tasks/broadcast.py` |
| `fetch_and_save_billz_products`, `update_billz_products_hourly` | task ✅ (beat) | `tasks/billz.py` |
| `create_amocrm_lead` | **dead — zero call sites** | **deleted** (git history archives it) |
| `get_broadcast_recipients` | plain fn ✅ (used sync by task + 3 views) | `tasks/broadcast.py` (re-exported) |
| `get_user_info` | plain fn ✅ | `InstagramService.get_user_info()` |
| `send_instagram_postback_next` | plain fn ✅ | `InstagramService.send_step_template()` (HTTP only; DB state update stays in the task) |
| `get_all_billz_products`, `extract_relevant_fields` | plain fn ✅ | new `shared/addons/billz.py` (`fetch_all_products`, `_extract_relevant_fields`) |

## Compatibility contract (verified, nothing else changed)

- Every task pins `name="apps.integration.tasks.<func>"` → queue routing in
  `config/celery.py` and the beat schedule in `config/settings.py` are untouched, and
  in-flight queued messages resolve across deploys.
- `tasks/__init__.py` re-exports all tasks + `get_broadcast_recipients` + `WAIT_SECONDS`
  → all 11 enqueue sites in `views.py` (including the lazy import at the Billz view) work
  with **zero view changes**.
- Registry check: all 14 routed `apps.integration.tasks.*` names registered; beat entry
  resolves (encoded as `TaskRegistrationTests`).

## Bugs fixed along the way

| Severity | Bug | Fix |
|---|---|---|
| High | `process_instagram_comment` crashed with `AttributeError` when a recorded post had **no** `InstagramCommentResponse` (`response.is_respond_to_all_comments` on `None`) | Guard added; quiet no-op + regression test |
| High | Trigger-match branch for a *new latest post* called nonexistent methods `send_instagram_comment_reply` / `send_instagram_private_reply` / `send_instagram_postback` → guaranteed `AttributeError` | Normalized to the real `InstagramService` methods |
| Medium | `get_user_info` network error would kill the whole message task | Fail-soft: returns `{}` + test |
| Low | Broadcast statuses hardcoded (`'sending'`, `'completed'`, model default `'pending'`) | New `BroadcastStatuses` enum (no migration needed — values unchanged) |
| Low | `traceback.print_exc()` / mixed `logging.x` module calls / f-string logging | `logger.exception(...)` + lazy `%s` formatting throughout |

Readability: the triple-duplicated comment-response dispatch collapsed into
`_dispatch_comment_response()`; the "comment on an unrecorded post" branch extracted to
`_handle_new_media_comment()` with comments explaining the timestamp rule.

## Files changed

| File | Change |
|---|---|
| `apps/integration/tasks.py` | deleted (split into package) |
| `apps/integration/tasks/{__init__,telegram,instagram_messaging,instagram_comments,instagram_flows,collector,broadcast,billz}.py` | new — tasks moved, names pinned, docstrings/comments added |
| `apps/shared/addons/billz.py` | new — Billz API client (pagination, fail-soft) |
| `apps/shared/addons/instagram.py` | + `get_user_info`, `send_step_template`, module logger |
| `apps/shared/addons/enums.py` | + `BroadcastStatuses` |
| `apps/integration/models.py` | `Broadcast.status` default via enum (same value, no migration) |
| `config/celery.py` | − dead `create_amocrm_lead` route |
| `apps/integration/tests.py` | patch paths moved to submodules; 6 new tests |
| `apps/integration/tests/` | removed (empty, untracked, shadow-prone next to `tests.py`) |

## Tests

New: `TaskRegistrationTests` (2 — name/routing contract), comment-without-config
regression, `get_user_info` fail-soft, Billz client pagination + fail-soft.

```
Ran 22 tests in 0.706s
OK
```

`apps.shared` + `apps.assistant`: 70 tests, only 2 failures — both in
`MessageQuotaTests` (assistant quota logic, `apps/assistant/models.py:188`), pre-existing
uncommitted work-in-progress unrelated to this change (see
`2026-07-21-assistant-c1-message-quota-crash.md`).

## Open items (need a human decision)

1. **amoCRM lead push**: `create_amocrm_lead` was never wired to anything. If pushing new
   `Lead`s to amoCRM is a wanted feature, it should be reimplemented against a proper
   `shared/addons/amocrm.py` client and enqueued where `Lead` objects are created.
2. **Vendor HTTP still in `views.py`**: amoCRM OAuth/token-refresh (`views.py:1087-1391`)
   and Billz login (`views.py:1463`) remain inlined — natural next candidates for the new
   `shared/addons/amocrm.py` / `billz.py` modules.
3. `_fetch_latest_media()` in `tasks/instagram_comments.py` is still a raw Graph API call —
   could graduate to `InstagramService` with the others.
