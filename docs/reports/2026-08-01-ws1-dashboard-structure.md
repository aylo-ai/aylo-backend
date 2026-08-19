# WS-1 — Dashboard views & serializers split into packages

**Date:** 2026-08-01 · **Workstream:** WS-1 (readability / structure) ·
**Scope:** `apps/dashboard/views.py`, `apps/dashboard/serializers.py`

Behaviour-preserving refactor. No URL moved, no view class was renamed, no
serializer field changed, no response body or status code changed, no
permission class changed. Two 1000-line modules became domain packages, and the
copy-pasted list/retrieve/create/update/destroy bodies were collapsed into six
mixins local to the app.

## 1. Before / after structure

### `apps/dashboard/views.py` → `apps/dashboard/views/`

| Before | After | Lines | Contents |
|---|---|---|---|
| `views.py` — 1707 lines, 50 view classes, 2 helpers | `views/__init__.py` | 134 | re-exports every public name |
| | `views/base.py` | 20 | `get_client_ip`, `subscription_repr` |
| | `views/mixins.py` | 94 | **new** — the six response mixins (§3) |
| | `views/auth.py` | 54 | OTP send / verify |
| | `views/overview.py` | 191 | dashboard, enhanced stats, statistics, AI-cost breakdown, global search |
| | `views/system.py` | 76 | system-health check |
| | `views/users.py` | 237 | list, detail, toggle-active, change-role, export, bulk-action |
| | `views/assistants.py` | 206 | assistants, assistant files, prompt templates |
| | `views/conversations.py` | 112 | conversations, close, escalate, messages |
| | `views/transactions.py` | 173 | list, detail, refund, export, bulk-action |
| | `views/subscriptions.py` | 170 | list, detail, cancel, extend |
| | `views/integrations.py` | 56 | list, detail |
| | `views/leads.py` | 133 | list, detail, stats, export |
| | `views/audit.py` | 22 | audit-log list |
| | `views/notifications.py` | 51 | list, send |
| | `views/catalog.py` | 98 | balances, cards, features, pricing packages |

### `apps/dashboard/serializers.py` → `apps/dashboard/serializers/`

| Before | After | Lines | Contents |
|---|---|---|---|
| `serializers.py` — 939 lines, 30 classes/functions | `serializers/__init__.py` | 93 | re-exports every public name |
| | `serializers/common.py` | 51 | `StrictCharField`, `serialize_pricing_package`, `serialize_subscription` |
| | `serializers/auth.py` | 59 | OTP login serializers |
| | `serializers/overview.py` | 264 | dashboard, enhanced-stats, time-series statistics |
| | `serializers/users.py` | 105 | user detail/list, change-role, bulk-action |
| | `serializers/assistants.py` | 109 | assistant list/create, file upload, filter, prompt template |
| | `serializers/conversations.py` | 65 | conversation detail/list |
| | `serializers/transactions.py` | 35 | transaction, refund, bulk-action |
| | `serializers/subscriptions.py` | 63 | subscription read/write, extend |
| | `serializers/integrations.py` | 117 | integration list |
| | `serializers/leads.py` | 17 | lead |
| | `serializers/audit.py` | 21 | audit log |
| | `serializers/catalog.py` | 83 | pricing package detail, feature |
| | `serializers/notifications.py` | 16 | notification send |

Largest module is now **264 lines** (was 1707). Nothing exceeds the ~400-line
budget.

## 2. Import-path proof

Step one was a pure relocation, re-exported from both `__init__.py` files, and
the suite was run green before any cleanup started.

```
$ grep -rn "apps\.dashboard\.views\|apps\.dashboard\.serializers" --include=*.py apps/ config/ \
    | grep -v "^apps/dashboard/views/\|^apps/dashboard/serializers/"
apps/dashboard/test_response_contract.py:5:`apps.dashboard.views.mixins`.  (docstring, not an import)

$ grep -rn "patch(.*dashboard" --include=*.py apps/ config/
(no matches — no test patches any dashboard symbol)
```

`apps/dashboard/urls.py` uses `from apps.dashboard import views` and reaches
every view as `views.X`; all 50 names are re-exported, so the file is unchanged.
Machine-checked with an AST walk over the pre-split files:

```
$ python scratchpad/check.py
OK  apps.dashboard.views.DashboardAICostBreakdownView
... (50 view names + 2 helpers, 30 serializer names) ...
all old top-level symbols resolve from the package __init__
```

The single name that does *not* resolve is the deleted dead view (§4).

## 3. Cleanup applied after the green relocation

### 3.1 Deduplicated boilerplate → `apps/dashboard/views/mixins.py`

Six mixins, local to the dashboard app (`apps/shared/mixins.py` is WS-3's file
and was not touched). Each carries the message as a class attribute, so the
response text is byte-identical to before.

| Mixin | Replaces | Views collapsed |
|---|---|---|
| `DashboardListMixin` | 8-line paginated `list()` | 10 |
| `DashboardStatsListMixin` | 15-line `list()` + `stats` block | 5 |
| `DashboardCreateMixin` | 5-line `create()` | 3 |
| `DashboardRetrieveMixin` | 4-line `retrieve()` | 9 |
| `DashboardPartialUpdateMixin` | 6-line partial `update()` | 6 |
| `DashboardDestroyMixin` | 3-line `destroy()` | 7 |

Roughly **230 lines of duplication removed**. Stats are still computed before
pagination, `update` is still partial everywhere it was partial, and views that
never overrode a method (e.g. `DashboardConversationDetail.retrieve`, which
returns DRF's bare body) were left alone — that unwrapped body is pinned by a
test.

### 3.2 Hardcoded strings → `apps/shared/addons/enums.py`

| File | Was | Now |
|---|---|---|
| `serializers/integrations.py` | `PLATFORM_MAP` / `TYPE_LABELS` keyed on `'telegram'`, `'instagram'`, … | `IntegrationTypes.*.value` keys, `ConversationPlatforms.*.value` values |
| `serializers/integrations.py` | `if obj.integration_type != 'telegram'` | `IntegrationTypes.TELEGRAM.value` |
| `serializers/assistants.py` | `integration_type='telegram'/'instagram'/'website'` | `IntegrationTypes.*.value` |

### 3.3 Other

- `f'/transactions'` (f-string with no placeholder) → `'/transactions'`.
- `from apps.integration.models import Integration` moved out of a serializer
  `Meta` body to module level.
- `import redis`, `from django.db import connection`, `from django.conf import
  settings` hoisted out of `DashboardSystemHealthView.get`. The `config.celery`
  and `default_storage` imports stay inline — the first is deliberately lazy
  (circular import), the second sits inside a `try` whose failure is part of the
  health report.
- `pyflakes apps/dashboard/` is clean: no unused imports or names anywhere in
  the two packages.

### 3.4 What was deliberately *not* done

- **N+1 queries left untouched** — WS-5 owns them, list in §6.
- **User-facing text not wrapped in `_()`.** `apps/shared/tests/test_i18n_catalogs.py::test_every_translatable_string_has_a_catalog_entry`
  fails the moment a new `_()` msgid has no entry in `locale/*/LC_MESSAGES/django.po`,
  and the five catalogs are outside WS-1's file ownership. ~60 English dashboard
  messages are affected. Handed to the i18n-translator — see §7.
- **No `Response(...)` to convert** — every dashboard endpoint already used
  `success_response` / `error_response`. The three CSV exports correctly return
  `HttpResponse`.

## 4. Deletions, with no-caller proof

| Deleted | Where it lived | Proof |
|---|---|---|
| `DashboardCommentResponseList` | old `views.py` L1135–1144, under a "kept for backward compat" banner | `grep -rn "DashboardCommentResponseList" .` → only its own definition and the `__init__` re-export. **No URL route** in `apps/dashboard/urls.py`, no import anywhere in `apps/` or `config/`. Unreachable over HTTP, so removing it cannot change API behaviour. |
| `apps/dashboard/tests/` | empty directory containing only `__pycache__` | No `__init__.py`, no test modules; sat next to `tests.py` where it can only confuse discovery. `git ls-files apps/dashboard/tests` → empty. |

`DashboardSerializer.Meta.fields` was **kept** although a plain
`serializers.Serializer` ignores `Meta` — it documents the payload and deleting
it buys nothing.

## 5. Files changed

| File | Change |
|---|---|
| `apps/dashboard/views.py` | **deleted** → `apps/dashboard/views/` (16 modules) |
| `apps/dashboard/serializers.py` | **deleted** → `apps/dashboard/serializers/` (14 modules) |
| `apps/dashboard/views/mixins.py` | **new** — six response mixins |
| `apps/dashboard/views/base.py` | **new** — `get_client_ip`, `subscription_repr` |
| `apps/dashboard/test_response_contract.py` | **new** — 10 tests pinning the mixin-driven contract |
| `apps/dashboard/tests/` | **deleted** — empty stale directory |
| `apps/dashboard/urls.py` | **unchanged** |
| `apps/dashboard/filters.py` | **unchanged** — no filter had to move |
| `apps/dashboard/tests.py` | **unchanged** by WS-1 (the modifications in the tree predate it) |

## 6. N+1 queries — handed to WS-5

Every one of these was **left exactly as found**. Ordered by blast radius
(queries per row × whether it is a list endpoint).

| Endpoint | Serializer / method | Cost per row |
|---|---|---|
| `GET /integrations/` | `DashboardIntegrationListSerializer` — `get_conversation_count`, `get_message_count`, `get_lead_count`, `get_last_message_time`, `get_telegram_groups` (`.exists()` + `.all()`) | **~6** |
| `GET /pricingpackages/` | `DashboardPricingPackageDetailSerializer` — `get_subscribers_count`, `get_active_subscribers`, `get_total_assistants`, `get_total_conversations`, `get_total_messages`, `get_total_tokens_used` (six independent aggregates) | **6** |
| `GET /assistants/` | `DashboardAssistantListSerializer.get_integrations` — three `.exists()` calls | 3 |
| `GET /users/` | `DashboardUserListSerializer.get_subscription` + `get_total_used_token_count` — `obj.subscription` then `subscription.pricing_package`; the view has **no** `select_related`/`prefetch` | 2–3 |
| `GET /subscriptions/` | `DashboardSubscriptionSerializer.get_user` (`obj.users.count()` then `obj.users.first()`) + `get_pricing_package`; view is a bare `Subscription.objects.all()` | 3 |
| `GET /conversations/` | `DashboardConversationListSerializer.get_message_count` — `obj.messages.count()` | 1 |
| `GET /prompts/` | `DashboardPromptTemplateSerializer.get_assistants_count` — `obj.assistants.count()` | 1 |
| `GET /messages/` | `DashboardMessageList` has no `select_related`; `MessageSerializer` dereferences `conversation` | 1 |
| `GET /users/<id>/` | `DashboardUserSerializer` — `get_assistants`, `get_transactions`, `get_conversation_and_message` (3 queries + full message iteration), and `get_integrations` which loops assistants and hits `integrations.all()` per assistant | 1 + N (detail only) |
| `GET /conversations/<id>/` | `DashboardConversationSerializer` — `get_message_price` counts *and* iterates, `get_message_count` repeats the same `.count()`, `get_messages` loads all messages | 4 (detail only) |

Two structural notes for WS-5:

- `get_message_price` and `get_message_count` on `DashboardConversationSerializer`
  issue the **same** `obj.messages.count()` twice — one `annotate` serves both.
- `DashboardIntegrationListSerializer`'s four counters differ only by which
  model they count and whether `PLATFORM_MAP` narrows by platform; they are a
  natural single annotated queryset.

## 7. Open items for a human

| Item | Why it needs a decision |
|---|---|
| ~60 dashboard response messages are unwrapped English | Wrapping them in `_()` requires msgids in all five `locale/*/LC_MESSAGES/django.po`, or `test_i18n_catalogs` fails. Locale files are the i18n-translator's; this is a separate, catalog-coupled task. |
| `AuditLog.action` / `target_type` are free-text | `'update'`, `'refund'`, `'bulk_delete'`, `'user'`, `'transaction'` … are hardcoded at ~20 call sites with no enum. Adding `AuditActions` / `AuditTargets` means editing `apps/shared/addons/enums.py` (WS-3's file) and arguably `dashboard/models.py` choices (WS-7's file). Left for a later, single-owner pass. |
| `DashboardIntegrationDetail` PATCH rejects a valid payload | `IntegrationSerializer.validate` answers `400 "Assistant topilmadi"` for an admin editing another user's integration. Pre-existing (the update body is byte-identical to before the split) and it lives in `apps/integration/` — WS-2/WS-4 territory. Flagged, not touched. |

## 8. Test result

The pre-existing suite is unedited. `apps/dashboard/test_response_contract.py`
adds 10 tests that pin the exact message strings, status codes, envelope shapes
and `stats` keys of every endpoint the mixins now drive.

```
$ .venv/bin/python manage.py test apps --keepdb
Using existing test database for alias 'default'...
Found 272 test(s).
System check identified no issues (0 silenced).
........................................................................
........................................................................
........................................................................
........................................................................
----------------------------------------------------------------------
Ran 272 tests in 10.598s

OK
Preserving test database for alias 'default'...
```

Baseline at the start of WS-1 was 249 green. The count reached 272 because
WS-3 and the other wave-1 streams landed tests in parallel; 10 of the new tests
are WS-1's. The whole-suite run confirms no other app's imports were broken.
