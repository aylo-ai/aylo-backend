# WS-2 — `apps/integration/views.py` → package

**Date:** 2026-08-01 · **Workstream:** WS-2 (readability / structure) ·
**Discipline:** behaviour-preserving refactor. No feature added, no response body
changed, no permission class touched, no queryset scoping added or removed.

## 1. Outcome

| | Before | After |
|---|---|---|
| Files | 1 (`views.py`) | 12 (`views/` package) |
| Lines | 1632 in one module | 1814 across 12 modules (largest 389) |
| View classes | 33 | 33 — **identical set**, verified against `HEAD` |
| Modules over 400 lines | 1 | 0 |
| Duplicated `get_queryset` bodies | 9 | 0 (one mixin) |
| Test suite | 249 green | 272 green |

The line total rises because each module carries its own imports, a docstring and
the class-level comments that were previously buried mid-file.

## 2. Before / after structure

| Module | Lines | Contents |
|---|---|---|
| `views/__init__.py` | 92 | Re-exports all 33 view classes; `__all__` |
| `views/mixins.py` | 25 | `IntegrationOwnedQuerysetMixin` (new, app-local) |
| `views/integrations.py` | 134 | `IntegrationListView`, `IntegrationListCreateView`, `IntegrationRetrieveUpdateDestroyView`, `SendUserMessageView`, `SendIntegrationMessageView` |
| `views/instagram_webhook.py` | 211 | `InstagramWebhookView` (Meta-facing) |
| `views/instagram_oauth.py` | 239 | `InstagramCallbackView`, `InstagramDeauthorizeView`, `InstagramDataDeletionView`, `parse_signed_request` |
| `views/telegram.py` | 166 | `TelegramWebhookView` (Telegram-facing), `TelegramGroupListView`, `TelegramGroupUpdateDestroyView` |
| `views/instagram_media.py` | 80 | `InstagramPostListView`, `InstagramMediaRetrieveView` |
| `views/comment_automation.py` | 107 | `CommentTriggerWord*` (2), `InstagramCommentResponse*` (2) |
| `views/flows.py` | 210 | `Flow` / `Step` / `Transition` / `CommentResponseButton` views (7) |
| `views/broadcasts.py` | 109 | `BroadcastListCreateView`, `BroadcastRecipientsCountView`, `BroadcastRecipientsListView` |
| `views/amocrm.py` | 389 | `AmoCRMOAuthInstallView`, `AmoCRMOAuthHandlerView` (amoCRM-facing), `AmoCRMTokenRefreshView`, `AmoCRMSetPipelineView` |
| `views/billz.py` | 52 | `BillzSecretTokenHandlerView` |

## 3. Contract preservation — evidence

| Check | Result |
|---|---|
| Class set vs `git show HEAD:apps/integration/views.py` | **identical**, 33 = 33 |
| Every class importable as `from apps.integration.views import X` | yes (33/33) |
| Integration routes resolved from the URLconf | 32, each to the same view class |
| `/api/v1/integration/instagram/webhook/` | → `InstagramWebhookView` ✅ |
| `/api/v1/integration/telegram/webhook/<str:bot_token>/` | → `TelegramWebhookView` ✅ |
| `/api/v1/integration/amocrm/` | → `AmoCRMOAuthHandlerView` ✅ |
| `/api/v1/integration/assistant/<uuid:pk>/billz/` | → `BillzSecretTokenHandlerView` ✅ |
| `urls.py` | **unchanged** — still `import apps.integration.views as views` |

`urls.py` needed no edit at all: the package re-exports every name the module used
to expose.

### The mixin emits the same SQL

The nine `get_queryset` bodies collapsed into `IntegrationOwnedQuerysetMixin` were
compared against the original expressions query-by-query:

| View | Result |
|---|---|
| `IntegrationRetrieveUpdateDestroyView` | SQL byte-identical |
| `IntegrationListCreateView` | SQL byte-identical |
| `CommentTriggerWordRetrieveView` | SQL byte-identical |
| `InstagramCommentResponseRetrieveView` | SQL byte-identical |
| `InstagramMediaRetrieveView` | SQL byte-identical |
| `TransitionRetrieveUpdateDestroyView` | SQL byte-identical |
| `FlowRetrieveUpdateDestroyView` | SQL byte-identical |
| `StepRetrieveUpdateDestroyView` | SQL byte-identical |
| `CommentResponseButtonRetrieveUpdateDestroyView` | SQL byte-identical |
| `IntegrationListView` | same columns, same rows; the two `OR` operands are emitted in the opposite order (original wrote `Q(user) \| Q(assistant__user)`) |

## 4. Files changed

| File | Change |
|---|---|
| `apps/integration/views.py` | **deleted** — content relocated verbatim, then cleaned |
| `apps/integration/views/{__init__,mixins,integrations,instagram_webhook,instagram_oauth,telegram,instagram_media,comment_automation,flows,broadcasts,amocrm,billz}.py` | **new** |
| `apps/integration/urls.py` | **unchanged** |
| `apps/integration/tests.py` | 8 `mock.patch` target strings repointed — see §5. No assertion, fixture or test name changed. |

## 5. The one thing a package split cannot preserve: patch targets

`mock.patch("apps.integration.views.redis_client")` patches the attribute on the
*package* object. Once the view lives in `views/instagram_webhook.py` it binds its
own module global, so the patch becomes a **silent no-op** — the view would talk to
the real Redis and the assertions would fail. Re-exporting `redis_client` from
`__init__.py` would make the target "resolve" while still patching nothing, which is
strictly worse than an error: a test that passes while testing nothing.

So the targets were repointed at the module that actually owns the binding. Same
collaborator, same assertions, same meaning:

| tests.py | Was | Now |
|---|---|---|
| ×4 | `apps.integration.views.redis_client` | `apps.integration.views.instagram_webhook.redis_client` |
| ×3 | `apps.integration.views.process_collected_messages` | `apps.integration.views.instagram_webhook.process_collected_messages` |
| ×1 | `apps.integration.views.http` | `apps.integration.views.instagram_oauth.http` |
| ×1 | `apps.integration.views.instagram_service` | `apps.integration.views.instagram_oauth.instagram_service` |
| ×1 | `from apps.integration import views as integration_views` | `from apps.integration.views import integrations as integration_views` |

`LOGGER = "apps.integration.views"` (line 450) needed **no** change: the five
fall-through log assertions still pass because `apps.integration.views.instagram_webhook`
is a child logger and propagates to the parent that `assertLogs` attaches to.

### A deferred import that turned out to be load-bearing

Hoisting `from apps.integration.tasks import send_broadcast_task` to module scope in
`broadcasts.py` broke `test_broadcast_is_not_dispatched_before_the_row_commits`: the
test patches `apps.integration.tasks.send_broadcast_task`, which only takes effect if
the view resolves the name at call time. **Reverted** — all four task imports in
`broadcasts.py` / `billz.py` are back inside their methods, now with a comment saying
why so nobody "cleans" them up again.

## 6. Cleanup applied

| Item | Detail |
|---|---|
| 9× duplicated `get_queryset` | → `IntegrationOwnedQuerysetMixin` with a declarative `owner_path`; SQL proven unchanged (§3) |
| 2× identical nested `parse_signed_request` (~40 lines each) | → one module-level function in `instagram_oauth.py` |
| Log line dumping the whole Instagram `entry` | removed — it duplicated the structured log directly below it, which is explicitly commented "Shape only — never the message body, which is customer content" |
| Log line dumping the whole `messaging` payload on an unknown account | removed — same reason; the structured `"Integration not found for Instagram account %s"` beside it is kept and is the one tests assert on |
| 4× f-string logging | → lazy `%s` (CLAUDE.md §3) |
| Function-level `PermissionDenied` / `check_bot_in_group` imports | hoisted in `telegram.py` |
| Function-level `Assistant` import in the amoCRM handler | hoisted (`billz.py` already imported it at module scope; no cycle — `tasks` never imports `views`) |
| Unused `logging` / `logger` / `Q` imports in 6 new modules | removed; `pyflakes` clean across the package |

Already compliant, nothing to do: **no bare `Response(...)`** anywhere in the file,
and every status/type string already went through `IntegrationTypes`.

## 7. Deletions, with no-caller proof

| Symbol | Proof | Action |
|---|---|---|
| `logger.info(f"...received for account: {account_id}, {entry}")` | duplicate of the structured log 3 lines below; `grep -rn "received for account" apps/` → no test references | deleted |
| `logger.warning(f"...unknown account:{messaging}")` | `grep -rn "unknown account" apps/` → only `"comment for unknown account"` is asserted (a different, retained line) | deleted |
| inner `parse_signed_request` ×2 | byte-identical bodies, differing only in one log string; no external caller (nested functions) | merged into one |
| `CommentResponseButtonListCreateView` | **unrouted**: absent from the resolved URLconf; `grep -rn` finds no importer outside its own re-export; `git log -S` on `urls.py` shows it was *never* routed | **NOT deleted — see below** |

### `CommentResponseButtonListCreateView` — recommended deletion, not performed

It is dead by every measure and is also a latent cross-tenant leak: an unscoped
`ListCreateAPIView` over *all* `CommentResponseButton` rows behind bare
`IsAuthenticated`. If anyone ever wires a URL to it, it leaks every tenant's buttons.

I deleted it, and `test_catalogs_carry_no_entries_for_deleted_code` correctly failed:
removing it orphans two msgids — `'Tugma muvaffaqiyatli yaratildi'` and
`'Tugmalar muvaffaqiyatli olindi'` — in all five `locale/*/LC_MESSAGES/django.po`
catalogs. Those catalogs are **owned by another workstream and were being modified
concurrently**, so I restored the class rather than edit files outside my scope.

**To finish this (2 minutes, once `locale/` is free):** delete the class from
`apps/integration/views/flows.py` and its two entries from `views/__init__.py`, then
remove those two msgids from the five catalogs. The class carries a comment pointing
here.

## 8. Handoff to WS-4 — class-level querysets

Per instruction, **no scoping was added or removed**. 18 view classes carry a
class-level `queryset`. Grouped by what actually gates them today:

### 8a. Unscoped — `objects.all()` reaches every tenant's rows

| View | Model | Route | Kind | Note |
|---|---|---|---|---|
| `TelegramGroupUpdateDestroyView` | `TelegramGroupIntegration` | `/telegram-group/<uuid:pk>/` | **DETAIL — retrieve/update/destroy** | Has a `get_object()` guard, but it is `if integration.assistant and integration.assistant.user != request.user`. When `integration.assistant` is **None** the check is skipped entirely — an integration owned via `Integration.user` alone is unguarded. Highest-priority item here. |
| `CommentTriggerWordListCreateView` | `CommentTriggerWord` | `/trigger-words/` | create-only | `queryset` unused by `CreateAPIView`; but creation is unvalidated against the caller's ownership. |
| `BillzSecretTokenHandlerView` | `Integration` | `/assistant/<uuid:pk>/billz/` | create-only | `queryset` unused by create; the view checks `Assistant.objects.filter(id=assistant_id).exists()` **without** checking the assistant belongs to the caller. |
| `CommentResponseButtonListCreateView` | `CommentResponseButton` | *(none)* | list/create | Dead — see §7. Unreachable today. |

### 8b. Filtered by a URL parameter only — no owner check (IDOR candidates)

These have a `get_queryset` so they look scoped, but none of them constrains by
`request.user`:

| View | Model | Route | What it filters on |
|---|---|---|---|
| `InstagramFlowTransitionListCreateView` | `Transition` | `/comment-response/flow/<uuid:pk>/transition/` | **Returns `self.queryset.all()` — every transition globally — whenever the flow id merely exists.** Worst of this group. |
| `InstagramCommentResponseListCreateView` | `InstagramCommentResponse` | `/<uuid:integration_id>/instagram/comment-responses/` | `integration_id` from the URL |
| `InstagramCommentResponseFlowListCreateView` | `Flow` | `/comment-responses/<uuid:pk>/flow/` | `comment_response_id` from the URL |
| `TelegramGroupListView` | `TelegramGroupIntegration` | `/integration/<uuid:pk>/telegram-group/` | `integration_id` from the URL |

### 8c. Owner-scoped via `IntegrationOwnedQuerysetMixin` (no action expected)

`IntegrationListView`, `IntegrationListCreateView`, `IntegrationRetrieveUpdateDestroyView`,
`CommentTriggerWordRetrieveView`, `InstagramCommentResponseRetrieveView`,
`InstagramMediaRetrieveView`, `TransitionRetrieveUpdateDestroyView`,
`FlowRetrieveUpdateDestroyView`, `StepRetrieveUpdateDestroyView`,
`CommentResponseButtonRetrieveUpdateDestroyView`.

WS-4 gains a single place to change the ownership rule: `views/mixins.py`. Adding
scoping to anything in 8a/8b is now a two-line change — mix the class in and declare
`owner_path`.

## 9. Test result

Baseline before any change: **249 tests, OK**.

```
$ .venv/bin/python manage.py test apps --keepdb
Using existing test database for alias 'default'...
Found 272 test(s).
System check identified no issues (0 silenced).
........................................................................
........................................................................
........................................................................
................................................................
----------------------------------------------------------------------
Ran 272 tests in 11.853s

OK
Preserving test database for alias 'default'...
```

The count rose 249 → 272 because WS-3 landed new payment tests while this ran; all
pass. `apps.integration` alone: **55/55 OK**.

## 10. Open items for a human

| Item | Why it needs you |
|---|---|
| Delete `CommentResponseButtonListCreateView` + its 2 orphaned catalog msgids | Cross-workstream: needs `locale/*.po`, which WS-2 does not own (§7). |
| `TelegramGroupUpdateDestroyView.get_object` skips its owner check when `integration.assistant is None` | Left exactly as found — WS-4 owns the fix. Flagged because it is easy to read as already-guarded. |
| `if is_approving is True or is_approving == 'true' or is_approving == True:` in `telegram.py` | Redundant first clause. Left untouched: it is an authorization/approval path WS-4 is about to audit, and an equivalent-but-rewritten boolean would only make their diff noisier. |
| Bare English strings in `amocrm.py` and the Meta deauthorize/data-deletion handlers | Not wrapped in `_()`. Deliberate: `test_i18n_catalogs.py` requires every `_()` msgid to exist in all five catalogs, so wrapping them is an i18n-workstream change, not a structural one. |
| `InstagramFlowTransitionListCreateView` returning all transitions globally (§8b) | Reads like a placeholder rather than an intended contract; needs a product decision on what it *should* return before WS-4 constrains it. |
