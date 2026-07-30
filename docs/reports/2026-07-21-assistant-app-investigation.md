# Investigation Report — `apps/assistant/`

**Date:** 2026-07-21
**Scope:** `models.py`, `serializers.py`, `views.py`, `tasks.py`, `utils.py`,
`filters.py`, `urls.py` (read in full; cross-checked `shared/models.py`,
`shared/mixins.py`).
**Status:** investigation only — no code changed yet. Fix order proposed at the end.

This app is the core domain: assistants, conversations, messages, leads, knowledge
base, and follow-ups. It is functional but carries several **crash-level bugs**,
**cross-tenant data-access holes**, and a set of **N+1 / missing-index** performance
problems that will worsen with scale.

---

## 🔴 Critical — crashes & security

### C1. `Message.save()` crashes for any owner without a subscription
`models.py:174-195`. On every assistant message:
```python
subscription = assistant_user.subscription
if subscription.remained_request_count > 0:   # AttributeError when subscription is None
```
`User.subscription` is a nullable FK. If the assistant's owner has no subscription,
**every assistant reply raises `AttributeError` inside `save()`**, failing the whole
turn. Also, the decrement `remained_request_count -= 1` is a read-modify-write —
two concurrent messages **lose updates** (should be `F('...') - 1`). Quota logic
living in `Message.save()` also fires two extra writes per message
(`conversation.save()` + `subscription.save()`).

### C2. Broad IDOR / missing tenant scoping on conversation, message & lead views
Multiple views fetch by `pk` with no ownership filter, so **any authenticated user
can read/update/delete another tenant's data**:
- `ConversationRetrieveView.get_object` → `queryset.get(pk=...)` (no owner filter; also raises `DoesNotExist` → **500 instead of 404**). `views.py:139`
- `LeadRetrieveView`, `ConversationMessagesListView`, `MessageBulkReadView` — filter only by the id in the URL, not by the requesting user.
- `ExportLeadsView` (`views.py:445`) exports leads for **any** `assistant_id` — cross-tenant lead dump.

### C3. `MessageListCreateView` is `AllowAny`
`views.py:168`. Message **create and list are unauthenticated**. Anyone can POST
messages to any conversation id — which runs the agent and **burns the owner's
tokens** — and can read any conversation's full history. Even if meant for the
website widget, there is no assistant/token/origin check.

### C4. Model-mismatched / broken views
- `MessageRetrieveView`: `queryset = Assistant.objects.all()` with `MessageSerializer` — retrieving a "message" actually loads an **Assistant**. `views.py:182`
- `SettingsListCreateView` / `SettingsRetrieveView`: `queryset = Assistant.objects.all()` with `SettingsSerializer` — same mismatch; these endpoints don't do what they claim. `views.py:223,242`

### C5. `ExportLeadsView` writes files to CWD and never cleans them
`views.py:453` / `serializers.py:528`: `wb.save("leads_export_<date>.xlsx")` writes
into the process working directory with a **per-day fixed filename** (concurrent
exports overwrite each other) and the file is **never deleted** → disk growth.
Should use `tempfile` + cleanup.

---

## 🟠 High — correctness

### H1. Dashboard message path diverges from the real orchestrator
`MessageSerializer.create` (`serializers.py:227`) calls `agent.run()` directly and
creates the assistant `Message`, but **never publishes to the websocket** — unlike
`agent.respond()`, which stores *and* publishes. Dashboard-originated replies don't
reach connected clients. It also re-implements orchestration that already lives in
`respond()`, and trusts a client-supplied `sender` (a client can POST
`sender="assistant"`).

### H2. Search / ordering on fields that don't exist → 500
`ConversationListCreateView` declares `search_fields = ['assistant__name',
'session_id']` and orders on `session_id`; `MessageListCreateView` searches
`'message'`. Neither `Conversation.session_id` nor `Message.message` exists, so any
`?search=`/`?ordering=` request **throws**. `views.py:107,165`

### H3. Follow-up template uses unbounded `str.format`
`tasks.py:294`: `template.format(...)`. A stray `{` or `{0.__class__}` in an
admin-set `message_template` will crash the send loop or expose internals. Guard it.

---

## 🟡 Optimization — performance & scale

### O1. N+1 queries
- `AssistantSerializer.get_integrations` runs **3 `.exists()` per assistant** on every list. `serializers.py:64`
- `ConversationSerializer.to_representation` runs a `.order_by().first()` **per conversation** for `last_message`. `serializers.py:137`
- `AssistantTokenStatsView` aggregates **once per assistant in a loop** — collapsible to a single grouped query. `views.py:474`
- `daily_statistics_assistant` **re-fetches the same assistant** with `Assistant.objects.get(id=...)` inside two helpers that already receive it. `tasks.py:85,103`

### O2. Missing indexes on hot paths
- `Conversation`: the per-message lookup `filter(assistant, user_id, token)` and the
  `ordering = ['-updated_time']` list are **unindexed** — seq scans as rows grow.
  Add `(assistant, user_id, token)` and `updated_time`.
- `Message`: only `created_time` is indexed, but nearly every query is
  `filter(conversation).order_by('-created_time')` → add composite
  `(conversation, created_time)`.
- `Lead`: filtered by `assistant`, `platform`, `created_time`, `username`, `status`
  — no indexes.

### O3. `ConversationRetrieveSerializer` uses `.last()` without ordering
`serializers.py:174`: `instance.messages.last()` relies on undefined ordering →
wrong/nondeterministic "last message". Use `.order_by('-created_time').first()`.

### O4. Quota write-amplification (see C1)
Move quota decrement out of `Message.save()` into the agent/orchestration layer, use
`F()` expressions, and bump `conversation.updated_time` with a single `update()`.

---

## 🧹 Dead code (verified — remove per CLAUDE.md §4)
| Item | Location | Evidence |
|---|---|---|
| `save_uploaded_file` task | `tasks.py:27` | no callers |
| `AssistantFileGoogleDocSerializer` + commented view/url | `serializers.py:451`, `views.py:388`, `urls.py:10` | only referenced by commented-out code |
| `Conversation.thread_id` field | `models.py:119` | never assigned anywhere; legacy Assistants-API leftover, still exposed in API responses |
| `Assistant.assistant_id` field | `models.py:83` | never assigned; `__str__` prints `"None - name"` |
| `Conversation.save()` override | `models.py:130` | no-op (only calls super) |
| Debug `print()`s | `tasks.py` (many), `views.py:219,381` | leftover logging |
| Duplicate content/audio check | `serializers.py:211` & `222` | same check twice |

---

## Proposed fix order (step by step)
1. **C1** — guard `Message.save()` against `None` subscription, switch to `F()` decrement. *(stops live crashes)*
2. **C2 + C3 + C4** — scope conversation/message/lead views to the requesting user; fix `AllowAny`; fix the model-mismatched views; 404 instead of 500.
3. **C5** — temp-file + cleanup for lead export.
4. **H1/H2/H3** — route dashboard replies through `respond()`; fix/remove bogus search fields; harden the follow-up template.
5. **O1–O4** — prefetch/annotate away N+1s; add the migration with the missing indexes; de-amplify `Message.save()`.
6. **Dead-code sweep** — remove the verified items above (+ tests).

Each step ends with tests + a green run + a change report, per CLAUDE.md.
