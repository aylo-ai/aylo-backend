# WS-4 — security audit: `apps/integration/**` + `apps/assistant/**`

**Date:** 2026-08-01 · **Workstream:** WS-4 (security) · **Depends on:** WS-2
(operates on the new `apps/integration/views/` package).

Scope audited: every view, serializer, gateway and task under `apps/integration/`
and `apps/assistant/`. 19 findings; 18 fixed, 1 (shared trigger-word rows) needs a
model change owned by WS-7 and is listed as an open item.

**Test suite: 272 → 299, green.** 27 new tests, every one asserting the denial *and*
the owner's success in the same test. Each new tenancy test was re-run against the
pre-fix code and **fails** there (§6).

---

## 1. Findings — Critical

### C1 · `/amocrm/refresh/` handed any authenticated user another tenant's CRM token

`AmoCRMTokenRefreshView` resolved its integration with
`Integration.objects.filter(id=integration_id, integration_type=AMOCRM).first()` —
no owner predicate — and then **returned the freshly minted `access_token` in the
response body**.

**Exploit:** any account with a JWT posts `{"integration_id": "<victim's>"}` and gets
back a live bearer token for the victim's amoCRM: every lead, contact and deal, read
and write. It also rotates the victim's refresh token as a side effect.

**Fix:** `owned_amocrm_integration()` (owner-scoped, 404 otherwise) and the access
token is no longer in the response. **Contract change — called out in §4.**

### C2 · Bind your own bot to another tenant's assistant

`IntegrationCreateSerializer.validate` resolved the URL's assistant with
`Assistant.objects.filter(id=assistant_id).first()`. The list half of
`IntegrationListCreateView` was owner-scoped by WS-2's mixin; the create half never was.

**Exploit:** `POST /api/v1/integration/assistant/<victim assistant id>/integration/`
with the attacker's own Telegram bot token. The attacker's bot is now served by the
victim's assistant — they DM it and read back the victim's system prompt and
knowledge-base content, billed to the victim's subscription quota.

**Fix:** `owned_assistants(user).filter(id=assistant_id)`.

### C3 · Same, through the Billz onboarding route, plus mass assignment

`BillzSecretTokenHandlerView` checked `Assistant.objects.filter(id=...).exists()` —
existence, not ownership — and `IntegrationSerializer.assistant` is a **writable**
field saved with a bare `serializer.save()`, so the request body could redirect the
new row even when the URL could not.

**Exploit:** `POST /assistant/<victim assistant id>/billz/` attaches the attacker's
Billz catalogue to the victim's assistant; `fetch_and_save_billz_products` then feeds
the attacker's product data into the victim's agent.

**Fix:** assistant resolved through `owned_assistants(request.user)` (404 otherwise)
and forced with `serializer.save(assistant=assistant)`.

---

## 2. Findings — High

| # | Where | Exploit | Fix |
|---|---|---|---|
| H1 | `TelegramGroupUpdateDestroyView` | The guard was `if integration.assistant and integration.assistant.user != request.user`. When `assistant` is NULL (an integration held through `Integration.user` alone) the check is **skipped entirely** → any authenticated user can `PATCH {"is_approved": true}` or `DELETE` another tenant's Telegram group. | `IntegrationOwnedQuerysetMixin`, `owner_path="integration"`; per-object guard deleted. |
| H2 | `TelegramGroupListView` | Filtered on the URL's integration id only → lists any tenant's group ids, titles and lead counts. | Same mixin, then the URL filter. |
| H3 | `InstagramPostListView` | `GET /integration/<victim id>/instagram/posts/` looked the integration up by id and then **spent its stored access token** to page up to 250 of the victim's Instagram posts back to the caller. | `owned_integrations(request.user)`. |
| H4 | `InstagramCommentResponseListCreateView` | Keyed off `integration_id` from the URL. GET reads another tenant's comment automation; **POST installs a new auto-reply on their verified Instagram account** — their profile then DMs its own commenters with attacker-chosen text. | One owner-scoped `_integration()` used by both halves; list → empty, create → 404. |
| H5 | `InstagramFlowTransitionListCreateView` | `get_queryset` did `return self.queryset.all()` whenever the flow id merely existed — **every `Transition` row in the database, all tenants**. POST wrote transitions into any flow. | Owner-scoped + restricted to the flow in the URL; create 404s on a flow the caller does not own. **Contract narrowing — §4.** |
| H6 | `InstagramCommentResponseFlowListCreateView` | Filtered on `comment_response_id` only, and the serializer's `get_object_or_404(InstagramCommentResponse, ...)` was equally unscoped → read and rewrite another tenant's comment-response flows. | Mixin (`owner_path="comment_response__integration"`) + ownership check before create. |
| H7 | `AmoCRMSetPipelineView` | Unscoped `integration_id` → mutate another tenant's amoCRM metadata and read their pipeline through their own token. | `owned_amocrm_integration()`. |
| H8 | `AmoCRMOAuthHandlerView` — SSRF | `referer` comes from the query string of an `AllowAny` endpoint and was interpolated into `https://{referer}/oauth2/access_token` **and** `https://{referer}/api/v4/account`, whose JSON body is echoed into the 200 response. Attacker-chosen outbound host, semi-blind read. | `is_amocrm_host()` allowlist (`amocrm.ru` / `amocrm.com` and their subdomains), applied to the callback and to the stored `subdomain` used by refresh/set-pipeline. Hosts carrying `/ \ @ : ? #` are rejected outright rather than parsed. |
| H9 | Full bot token in logs | `gateways/telegram.py` did `print(f"No integration found for bot token: {bot_token}")` and `tasks/telegram.py` did `logger.warning("... bot_token: %s", bot_token)`. A Telegram bot token is total control of the customer's bot, and this deployment ships a log viewer (Dozzle). `views/telegram.py` also logged `bot_token[-6:]`. | Tokens never logged; the webhook line now names the resolved integration id instead. |
| H10 | `AssistantSerializer.user` writable | `PATCH /chat/assistant/<own id>/ {"user": "<victim id>"}` silently transfers the assistant into the victim's account — it then eats the victim's 5-assistant quota and every integration hung off it validates and bills **the victim's** subscription (`IntegrationSerializer.validate` reads `assistant.user.subscription`). | `user` added to `read_only_fields`. Both server-side create paths pass `user=` to `save()`, which a read-only field does not block. |
| H11 | `InstagramCallbackView` — unauthenticated assistant binding | `assistant_id` arrived in the query string of an unauthenticated endpoint and was written straight onto the new `Integration`. Anyone completing Instagram OAuth with **their own** IG account could point it at another tenant's assistant; their DMs are then answered by the victim's agent, spending the victim's quota and reading back the victim's knowledge base. | The assistant is bound only when the caller is authenticated and `owned_assistants()` contains it; otherwise 404 (not 403 — no assistant-id oracle). **Deployment note in §5.** |

---

## 3. Findings — Medium / Low

| # | Sev | Where | Issue | Fix |
|---|---|---|---|---|
| M1 | Med | `SendIntegrationMessageView` | `integration.assistant.user != request.user` ignores `Integration.user` ownership and raises `AttributeError` — a **500**, not a refusal — whenever `assistant` is NULL. | Single owner-scoped lookup; status code and message unchanged. |
| M2 | Med | `ConversationRetrieveSerializer.assistant` writable | `PATCH /chat/conversation/<own id>/ {"assistant": "<victim's>"}` re-parents the conversation, pushing attacker-authored messages into the victim's inbox. The view's ownership check had already passed on the *original* parent. | `assistant` → `read_only_fields`. |
| M3 | Med | `MessageSerializer.conversation` writable on update | Same shape one level down: `PATCH /chat/message/<own id>/ {"conversation": "<victim's>"}` moves the message into another tenant's thread. | `validate()` drops `conversation` on the update path. |
| M4 | Med | amoCRM client secret cached in Redis | `AmoCRMOAuthInstallView` wrote `client_secret` into the `amocrm_oauth_state:*` blob, one copy per in-flight install. | Not stored; the callback reads `settings.AMOCRM_SECRET_KEY` and fails closed (500) if unset. |
| M5 | Med | No rate limit on unauthenticated surfaces | Instagram OAuth callback, amoCRM OAuth callback, Meta deauthorize / data-deletion — all `AllowAny`, all doing outbound HTTP or deletions, none throttled. | New `apps/integration/throttles.py`: `OAuthCallbackThrottle` and `MetaDataRequestThrottle`, 30/min per client address. Rates declared on the classes, so **no `config/settings.py` change** (owned by WS-3). Webhooks are deliberately left unthrottled — they authenticate every delivery and Meta disables a subscription that collects 429s. |
| L1 | Low | `AmoCRMSetPipelineView` | `pipeline_id` from the body is interpolated into the request path. | Rejected unless numeric. |
| L2 | Low | `FollowUpStageListCreateView.create` | Hand-rolled `Q(user=request.user) \| Q(user=request.user.created_by)`: with `created_by` unset the second leg is `Q(user=None)` and matches every **ownerless** assistant — the exact bug `owned_assistants()` exists to prevent. | Uses `owned_assistants()`. |
| L3 | Low | `MessageSerializer.create` | `transcribed_text, _, _ = media.transcribe_audio(...)` binds `_` (gettext) as a method-local, so the `_("Request obyekti kerak")` guard above it raises `UnboundLocalError` — a 500 where a 400 was intended. | Renamed to `_input_tokens, _output_tokens`. |

### Verified as already correct (no change)

| Surface | Why it is fine |
|---|---|
| `InstagramWebhookView` | HMAC-SHA256 over the raw body against `X-Hub-Signature-256`, `hmac.compare_digest`, **fails closed** when `INSTAGRAM_APP_SECRET` is unset. Verify handshake requires a configured `INSTAGRAM_VERIFY_TOKEN`. |
| `InstagramDeauthorizeView` / `InstagramDataDeletionView` | `parse_signed_request` verifies the Meta signature with `compare_digest` before anything is deleted. |
| `TelegramWebhookView` | The bot token in the path is the credential; only Telegram holds it. Resolved by DB lookup, not string comparison. |
| `IntegrationSerializer` / `IntegrationCreateSerializer` | `api_token` is already `write_only` (WS-earlier fix); no token is echoed on read. |
| `Broadcast*` views | Already owner-scoped on both the queryset and the create path. |
| Assistant/Conversation/Message/Lead/FollowUp list & detail views | Already scoped through `owned_assistants()`; the class-level `queryset = X.objects.all()` on each is overridden by `get_queryset`/`get_object`. Confirmed route by route. |
| Injection | No `.raw()`, `.extra()`, f-string SQL or `eval` anywhere in either app. |

---

## 4. Contract changes (deliberate — the change *is* the fix)

| Endpoint | Before | After | Why |
|---|---|---|---|
| `POST /integration/amocrm/refresh/` | `data: {access_token, expires_in}` | `data: {integration_id, expires_in}` | The access token is a bearer credential for the customer's whole CRM. The server stores it and uses it on the caller's behalf; nothing outside needs a copy, and returning it is what turned the missing ownership check into a one-request takeover. **A client reading `data.access_token` will break — check the frontend.** |
| `GET /integration/comment-response/flow/<pk>/transition/` | every `Transition` row in the database | that flow's transitions, owned by the caller | Returning all tenants' rows *was* the vulnerability. The in-code comment ("Return only transitions whose from_to step belongs to this flow") says this is what it was always meant to do. |
| `GET /integration/instagram/callback/?assistant_id=…` | bound the assistant unauthenticated | 404 unless the caller is authenticated and owns it | See §5. |
| `POST /integration/send/integration/<pk>/` | 404 when absent, 400 when not owned | 400 for both | Same message and code as the existing not-owned branch; stops the endpoint doubling as an integration-id oracle. |

Everything else — URLs, status codes, response envelopes — is unchanged.

---

## 5. Deployment note — read before shipping H11

`InstagramCallbackView` now refuses to bind `assistant_id` unless the request carries a
JWT for a user who owns that assistant.

- If `INSTAGRAM_REDIRECT_URI` points at the **frontend**, which then calls this API with
  the user's token: nothing changes. The view already read `request.user`, which only
  makes sense in that shape.
- If Meta redirects the **browser straight to this endpoint**, no JWT is attached and
  assistant-bound Instagram onboarding will start returning 404.

The automation-only path (`is_automation_only=true`, no `assistant_id`) is untouched and
still works unauthenticated.

The restrictive reading is implemented deliberately: the alternative is leaving a
cross-tenant assistant hijack open on an unauthenticated endpoint. **Confirm the value of
`INSTAGRAM_REDIRECT_URI` before deploy.**

---

## 6. Files changed

| File | Change |
|---|---|
| `apps/integration/views/mixins.py` | **+** `owned_integrations(user)` — the single definition of integration tenancy for the app. `IntegrationOwnedQuerysetMixin` untouched (WS-2 proved its SQL). |
| `apps/integration/views/telegram.py` | H1, H2 (mixin scoping, dead per-object guard removed), H9 (webhook log names the integration, not the token). |
| `apps/integration/views/instagram_media.py` | H3. |
| `apps/integration/views/comment_automation.py` | H4. |
| `apps/integration/views/flows.py` | H5, H6. |
| `apps/integration/views/amocrm.py` | C1, H7, H8, M4, L1. |
| `apps/integration/views/billz.py` | C3. |
| `apps/integration/views/integrations.py` | M1. |
| `apps/integration/views/instagram_oauth.py` | H11, M5. |
| `apps/integration/serializers.py` | C2. |
| `apps/integration/throttles.py` | **new** — M5. |
| `apps/integration/gateways/telegram.py` | H9; `print()` → lazy `%s` logger in the two functions touched; dead `chat_title` parameter dropped from `handle_bot_removed_from_group` (sole caller updated). |
| `apps/integration/tasks/telegram.py` | H9. |
| `apps/assistant/serializers.py` | H10, M2, M3, L3; two unused imports removed (`TelegramGroupIntegration`, `send_telegram_message` — `grep -rn` confirmed no caller and no patch target). |
| `apps/assistant/utils.py` | `owned_assistants()` moved here from `views.py` so serializers and the integration app can share one definition. |
| `apps/assistant/views.py` | Imports `owned_assistants` from `utils`; L2; unused `import os` and now-unused `Q` removed. |
| `apps/integration/tests.py` | **+20 tests** (§7). |
| `apps/assistant/tests.py` | **+7 tests** (§7). |
| `locale/{uz,ru,en,kk,ko}/LC_MESSAGES/django.po` | One orphaned msgid removed — see below. |

### The one file outside the workstream's tree

Deleting the dead `TelegramGroupUpdateDestroyView.get_object` orphaned the msgid
`"Bu guruhni boshqarish huquqi yo'q"`, which `test_catalogs_carry_no_entries_for_deleted_code`
fails on. The entry was removed from all five catalogs (a removal, no translation work,
no new msgids added anywhere in this workstream — every new denial path reuses an existing
string or DRF's own `NotFound`). Parity across the five catalogs is preserved.

## 7. New tests

All 27 assert **denial and legitimate success in the same test**.

| Class | Tests | Covers |
|---|---|---|
| `TenancyFixture` (base) | — | Two subscribed tenants; an integration held via `assistant`, one held via `user` with `assistant=NULL`, a Telegram group, comment response, flow, step, transition. |
| `TelegramGroupTenancyTests` | 2 | H1, H2 — stranger 404 on read/update/delete and the row survives; owner 200. Stranger's list empty, owner's has one row. |
| `CommentAutomationTenancyTests` | 4 | H4, H5, H6 — list/create denial per resource; the transition list returns *only* this flow's rows, not another tenant's. |
| `InstagramPostListTenancyTests` | 1 | H3 — stranger 400 **and `http.get` never called** (no token spent); owner 200 with the media. |
| `SendIntegrationMessageTenancyTests` | 1 | M1 — stranger 400 and no task queued; owner 200 and queued once. |
| `IntegrationCreateTenancyTests` | 1 | C2 — refused against the victim's assistant, accepted against their own. |
| `BillzTenancyTests` | 1 | C3 — refused for the victim's assistant; the owner's request that *names* the victim's assistant in the body still lands on their own. |
| `AmoCRMTenancyTests` | 2 | C1, H7 — stranger 404 with **no outbound call and the stored token unchanged**; owner 200, and the response contains neither `access_token` nor the token's value. |
| `AmoCRMCallbackHostTests` | 3 | H8 — off-domain referer 400 before any request leaves; smuggled authorities (`amocrm.ru.evil.com`, `evil.com@amocrm.ru`, `amocrm.ru:8080`, …) rejected; a genuine `repli.amocrm.ru` still proceeds to the exchange. |
| `InstagramCallbackAssistantBindingTests` | 3 | H11 — unauthenticated 404, other tenant 404, no row created; owner 200 and correctly bound. |
| `TelegramWebhookSecretHandlingTests` | 2 | H9 — unknown token 403; known token 200 and the log carries the integration id, not the token or any suffix of it. |
| `TelegramGatewaySecretHandlingTests` | 2 | H9 — unmatched and matched bot tokens both stay out of the log; the group is still created. |
| `MassAssignmentTenancyTests` | 3 | H10, M2, M3 — the tenancy field is ignored while the rest of the same PATCH still applies. |
| `FollowUpStageOwnershipTests` | 1 | L2. |
| `MessageCreateWithoutRequestTests` | 1 | L3. |

### Proof the tests are regressions, not decoration

Each fix was reverted in place and the corresponding tests re-run: **16 of 16 tenancy
tests failed** against the pre-fix code (8 in the first batch — Telegram group, amoCRM
refresh, Instagram callback, mass assignment; 8 in the second — comment automation,
flows, transitions, posts, send-message, integration create, Billz), then the code was
restored.

## 8. Test result

```
$ .venv/bin/python manage.py test apps --keepdb
Using existing test database for alias 'default'...
Found 299 test(s).
System check identified no issues (0 silenced).
.......................................................................................
.......................................................................................
.......................................................................................
........................................
----------------------------------------------------------------------
Ran 299 tests in 13.967s

OK
Preserving test database for alias 'default'...
```

```
$ .venv/bin/python manage.py test apps.integration apps.assistant --keepdb
Ran 111 tests in 7.331s

OK
```

Baseline entering WS-4 was **272, OK**. 299 = 272 + 27 new. No existing test was
modified.

## 9. Open items for a human

| Item | Why it needs you |
|---|---|
| **`INSTAGRAM_REDIRECT_URI`** | H11 makes assistant binding require an authenticated caller. Confirm the redirect URI points at the frontend (which forwards the JWT) and not at this API directly. §5. |
| **`data.access_token` removed from `/amocrm/refresh/`** | C1. Check the frontend does not read it. If some client genuinely needs to call amoCRM directly from the browser, that is a design change, not a field to put back. |
| **Shared `CommentTriggerWord` rows — NOT fixed** | `InstagramCommentResponseSerializer` does `CommentTriggerWord.objects.get_or_create(trigger_word=word)`, so two tenants using the word "narx" share one row. `PATCH`/`DELETE /trigger-words/<pk>/` then passes the ownership mixin (the caller legitimately references the row) while mutating the *other* tenant's automation. `InstagramMedia` has the same shape via its `unique=True` `media_id`, though media ids rarely collide across accounts. The root fix is a per-integration uniqueness constraint — a model change plus a data migration, owned by **WS-7**. A view-level guard would only turn the silent corruption into a confusing error. |
| **`CommentResponseButtonListCreateView` still present** | Dead and unrouted (WS-2 §7), and an unscoped list over every tenant's buttons if anyone ever wires a URL to it. Its two msgids are the only reason it survives. Now that this workstream has already touched `locale/`, deleting it is a 2-minute follow-up. |
| **`amocrm.py` / Meta handlers return bare English strings** | Not wrapped in `_()`. Left as WS-2 left them: wrapping them requires adding msgids with real translations to five catalogs, which is an i18n task, not a security one. |
| **amoCRM host allowlist is `amocrm.ru` + `amocrm.com`** | Kommo (`kommo.com`) is the same product internationally. If any customer is on a Kommo domain their OAuth will now be refused — add it to `AMOCRM_ALLOWED_DOMAINS` if so. Restrictive reading implemented. |
| **OAuth `state` is not deleted on a failed callback** | Only the success path calls `redis_client.delete`. A failed exchange leaves the state replayable for its remaining TTL (≤5 min). Low, and fixing it changes retry behaviour — flagged rather than changed. |
| **Ownerless integrations** (`assistant` and `user` both NULL) | Created by the automation-only Instagram path when the caller is unauthenticated. They are now invisible to every owner-scoped queryset — i.e. unmanageable through the API. Decide whether that path should require authentication too. |
