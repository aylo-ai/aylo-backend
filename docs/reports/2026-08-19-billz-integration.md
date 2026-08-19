# Billz integration: token refresh, sync status, and the frontend contract

**Branch:** `feat/billz-integration` · **Date:** 2026-08-19

Billz issues the merchant a long-lived **secret token**. It is worth nothing to the
API on its own: it must be exchanged at `/v1/auth/login` for a short-lived
**access token**, and that access token is the only credential `/v2/products`
accepts. The exchange happened exactly once, at connect time, and nothing ever
repeated it — so the catalogue mirror died silently the first time a token aged
out. This change moves authentication into the gateway, makes expiry a distinct,
recoverable event, and exposes sync state to the UI.

---

## 1. Issues found and fixed

### Blocking (the reason the integration was broken)

| # | Issue | Fix |
|---|---|---|
| B1 | The login call lived inline in `BillzSecretTokenHandlerView` (and a second copy in `IntegrationCreateSerializer.create`). The sync task had no way to authenticate, so it could only ever reuse a token that expires. | `apps.integration.gateways.billz.login(secret_token) -> Optional[str]`. Both call sites now go through it; no HTTP in a view or serializer. |
| B2 | `fetch_all_products` caught `RequestException` around `raise_status_for()`, so a 401 was swallowed like a network blip, `[]` was returned, and the task logged "No products fetched" and returned. Nothing was ever told the catalogue was stale. | `BillzAuthError` is raised on `401`/`403` (checked **before** `raise_for_status`, which would otherwise convert it into the fail-soft branch). Every other error keeps the existing fail-soft walk. |
| B3 | Nothing re-authenticated. | `fetch_and_save_billz_products` catches `BillzAuthError`, re-logs in with `integration.refresh_token` (the secret token), persists the new access token with `save(update_fields=['api_token'])` (the model appends `api_token_hash` itself), and retries the fetch **once**. A second refusal, a failed login, or a missing secret token records `auth_failed` and returns — it never raises and never loops. |
| B4 | **The secret token was never stored.** The connect view did `request.data['refresh_token'] = api_token`, but `refresh_token` is not a serializer field, so it was dropped on save (and the mutation would raise outright on a form-encoded, immutable `QueryDict`). Every Billz row created through this endpoint therefore has no recovery credential. | Tokens are passed as `serializer.save(api_token=..., refresh_token=...)` kwargs. A row with no `refresh_token` is reported as `auth_failed` with an explicit log line — see the migration note in §5. |
| B5 | `IntegrationCreateSerializer.create` stored `response['data']['refresh_token']` — a key Billz does not send — as the recovery credential, so the generic create endpoint produced rows that could never re-authenticate either. | That branch now calls `billz.login()` and stores the **secret** token in `refresh_token`, same as the dedicated endpoint. |
| B6 | Deleting a Billz integration orphaned its product file in the assistant's vector store forever: the file id lived only in `Integration.metadata`, so after the row was gone nothing could identify it. The agent kept answering from a disconnected POS. | `IntegrationRetrieveUpdateDestroyView.destroy` calls `_discard_billz_catalogue()` before delete — fail-soft (`knowledge_base.delete_file` logs and swallows its own errors). |
| B7 | The documented request body (`{"api_token", "name"}`) returned **400 `integration_type` required**, because `IntegrationSerializer` makes the model field required. Found by the new endpoint test. | The view fills `integration_type` (and defaults `name` to `"Billz"`) before validation, and forces the type again on save. The URL is the Billz endpoint; the type is not the caller's to choose. |

### Also fixed

| # | Issue | Fix |
|---|---|---|
| B8 | Reconnecting created a *second* Billz integration on the same assistant: two catalogue files in one vector store, two hourly syncs, and a status read that could resolve to either row. | Connect upserts: an existing Billz integration on that assistant is refreshed in place. Still `201`, same request and response shape (see §4 — flagged for the frontend). |
| B9 | `billz_products_updated_at` (an epoch float) had no reader anywhere. | Replaced by `billz_last_synced_at` (ISO 8601 UTC), and popped on write so old rows converge instead of carrying two disagreeing "last updated" values. |
| B10 | A crash anywhere in the task left the card stuck on `syncing` forever. | The outer `except` records `failed` (itself guarded). |

### Not fixed on purpose

`update_billz_products_hourly` **retries** `auth_failed` rows rather than skipping
them. `auth_failed` is also what a Billz outage answering `403` produces, and
skipping would park such an integration permanently until a human noticed. The
cost of retrying is one login round trip per hour.

---

## 2. Pre-existing damage found in `apps/integration/tests.py` (please read)

`apps/integration/tests.py` **did not parse** at `HEAD` on this branch — the whole
integration test suite was unrunnable, silently. A bad merge (`0a10357` /
`8def26b`) interleaved two class bodies. I repaired only enough to make the module
importable and statically sane:

| Damage | Repair |
|---|---|
| `test_the_known_token_is_accepted_and_never_logged` truncated mid-statement (`SyntaxError: '(' was never closed`), its tail spliced into `MetaSignedRequestTests`. | Tail restored from `4984394`; `MetaSignedRequestTests`' own assertion restored. |
| Three `MetaSignedRequestTests` methods stranded inside `TelegramGatewaySecretHandlingTests` (`self.integration`, `self.signed_request` undefined there). | Moved back into their class. |
| Two classes named `AmoCRMTenancyTests`; the later, stale one shadowed the earlier, correctly targeted one, so the *good* tenancy tests never ran. | Stale copy renamed `AmoCRMLegacyTenancyTests` with a docstring explaining what a human should do with it. |

**Still broken, needs a human (not Billz-related, so I did not guess):** 36 tests in
the merge-appended tail of `tests.py` predate the `views.py` → `views/` package
split and patch names that now exist only in the shadowed dead monolith:
`apps.integration.views.redis_client`, `...views.http`,
`...views.INSTAGRAM_CLIENT_SECRET`, and `from apps.integration.views import
webhook_replay_seen` / `WEBHOOK_DEDUP_TTL_SECONDS`. They fail with
`AttributeError` / `ImportError`. `webhook_replay_seen` exists **only** in
`apps/integration/views.py` — the webhook replay guard may have been dropped
entirely in the views split. That is worth checking before the next deploy.

**Related:** `apps/integration/views.py` (82 KB) and `apps/dashboard/views.py` +
`serializers.py` (110 KB) are dead — Python resolves the `views/` and
`serializers/` **packages** and never imports the modules. I did not delete them;
that is a separate, large, and reviewable change.

---

## 3. Files changed

| File | Change |
|---|---|
| `apps/shared/addons/enums.py` | New `BillzSyncStatuses` (`never_synced`, `syncing`, `synced`, `failed`, `auth_failed`). |
| `apps/integration/gateways/billz.py` | New `LOGIN_URL`, `AUTH_STATUS_CODES`, `BillzAuthError`, `login()`. `fetch_all_products` raises on 401/403, stays fail-soft otherwise. |
| `apps/integration/tasks/billz.py` | `record_sync_status()` (merges into `metadata`), `_fetch_products()` (re-login + one retry), `_utc_iso()`. Status transitions on every exit path. No new task names. |
| `apps/integration/views/billz.py` | `billz_status()` payload builder; `GET` status handler; `_payload()`; upsert connect; new `BillzSyncView`. |
| `apps/integration/views/integrations.py` | `_discard_billz_catalogue()` on `DELETE`. |
| `apps/integration/views/__init__.py`, `urls.py` | Export + route `BillzSyncView` at `billz/<uuid:pk>/sync/`. |
| `apps/integration/serializers.py` | `IntegrationCreateSerializer.create` uses the gateway; stores the secret token as `refresh_token`. |
| `apps/integration/tests_billz.py` | **New** — 43 tests. |
| `apps/integration/tests.py` | Merge-damage repair (§2); `BillzClientTests` → `SimpleTestCase`; `BillzTenancyTests` re-pointed at the gateway. |
| `apps/integration/tests_encryption.py` | `TelegramWebhookRegistrationTests` used a `mock.Mock()` user; `Q(user=<Mock>)` is not filterable, so the test failed on query construction before reaching its subject. Real `User` now. |
| `locale/{en,kk,ko,ru,uz}/LC_MESSAGES/django.po` | The three new user-facing strings, translated in all five catalogs. |

No migration: sync state lives in the existing `Integration.metadata` JSON.
No `config/celery.py` change: no new task names; `fetch_and_save_billz_products`
was already routed to the `sync` queue.

---

## 4. API contract as implemented

`data` is the **same flat object everywhere** (`connected` false ⇒ every other
field null/false):

```json
{"connected": true, "id": "<uuid>", "name": "Billz", "is_active": true,
 "sync_status": "synced", "last_synced_at": "2026-08-19T06:10:00Z", "product_count": 1423}
```

| Method & path | Code | `sync_status` in the response |
|---|---|---|
| `GET /api/v1/integration/assistant/<assistant_id>/billz/` | 200 | stored value, or `never_synced` |
| `POST /api/v1/integration/assistant/<assistant_id>/billz/` — body `{"api_token": "<SECRET>", "name": "Billz"}` | 201 | `syncing` (the first sync is queued) |
| `POST /api/v1/integration/billz/<integration_id>/sync/` — no body | 202 | `syncing` |
| `DELETE /api/v1/integration/integration/<id>/` (existing) | 204 | — |

- 404 on an assistant/integration the caller does not own (`owned_assistants()`,
  unchanged); 400 on a missing or rejected token.
- Tokens never appear in any response; asserted by test.
- Both writing endpoints queue the task in `transaction.on_commit`.

**Deviations the frontend must know about** (both keep the documented request and
`data` shapes):

1. **Connect returns `sync_status: "syncing"`**, not `never_synced` — it has just
   queued the first sync.
2. **Connect upserts.** A second POST for an assistant that already has a Billz
   integration refreshes that row (same `id`) instead of creating a duplicate.
   Still `201`. This is what makes the `auth_failed` → "Reconnect" call to action
   actually heal the row the hourly beat already knows about.
3. `name` is optional and defaults to `"Billz"`; `integration_type` must **not**
   be sent (it is ignored if it is).

---

## 5. Tests

43 new tests in `apps/integration/tests_billz.py`: login (success, non-200,
no `access_token`, network error, unparseable body, empty input),
`BillzAuthError` on 401/403 vs fail-soft on a connection error, mid-walk partial
results, bearer header, the re-auth + retry path (including that the refreshed
token is findable by its hash), `auth_failed` on failed re-login / missing
`refresh_token` / immediately-refused fresh token, `syncing` observed mid-flight,
`failed` on empty catalogue / failed index / unexpected exception, metadata merge
preserving `billz_products_file_id` and unrelated keys, all three endpoints
(shapes, no-credential-in-body, cross-tenant 404, non-Billz 404), and disconnect
cleanup.

### What actually ran

**Postgres is not available in this environment** (`.env` → `127.0.0.1:55432`,
nothing listening; the compose `postgres` service publishes no host port).

**A. No database — real settings, genuinely green:**

```
$ .venv/bin/python manage.py test apps.integration.tests_billz.BillzLoginTests \
    apps.integration.tests_billz.BillzFetchAuthTests \
    apps.integration.tests_billz.BillzStatusPayloadTests \
    apps.integration.tests.BillzClientTests
Found 16 test(s).
Skipping setup of unused database(s): default.
System check identified no issues (0 silenced).
................
----------------------------------------------------------------------
Ran 16 tests in 0.006s

OK
```

**B. DB-backed tests — green on an ephemeral SQLite harness, NOT verified on
Postgres:**

```
$ .venv/bin/python manage.py test apps.integration.tests_billz --settings=_sqlite_test_settings
Found 43 test(s).
...........................................
Ran 43 tests in 0.133s

OK
```

The harness is a throwaway settings module (deleted again, not committed):
SQLite `:memory:`, `MIGRATION_MODULES` returning `None` for every app so tables
come from the models (`AddIndexConcurrently` in migration `0043` is
Postgres-only), and `ArrayField` taught to round-trip through a text column
(`db_type` → `text`, JSON in/out, drop the `::type[]` placeholder). Nothing under
test touches an array field. **Treat B as unverified until it is run on Postgres**
with `.venv/bin/python manage.py test apps.integration.tests_billz --keepdb`. It
did earn its keep: it is what caught B7.

**C. Static checks:**

```
$ .venv/bin/python manage.py check
System check identified no issues (0 silenced).

$ .venv/bin/python -m pyflakes <11 changed files>
(no output)
```

**D. Wider run on the same harness** (`apps.integration`, 170 tests): 39 errors,
**all** pre-existing — 36 from the stale merge-appended region described in §2,
and 3 `raw_column` tests in `tests_encryption.py` that need real Postgres.
`apps.shared.tests.test_i18n_catalogs` still fails on 33 msgids and 11 orphans
that predate this change (none Billz); the three strings this change adds are in
all five catalogs. `apps.dashboard.test_response_contract` fails on
`Conversation.client_full_name ... cannot be queried with 'icontains'` — a real,
pre-existing dashboard search bug, unrelated to Billz.

---

## 6. Open items for a human

| # | Item |
|---|---|
| 1 | **Run the DB tests on Postgres.** `manage.py test apps.integration.tests_billz --keepdb`. |
| 2 | **Existing Billz rows have no `refresh_token`** (B4), so their first token expiry lands them in `auth_failed` and the UI will ask the merchant to reconnect. That is the intended behaviour, but it is user-visible: check how many rows are affected (`Integration.objects.filter(integration_type='billz')`) and consider warning those customers instead of waiting for the card to turn red. There is no way to back-fill — only the merchant has the secret token. |
| 3 | **An empty catalogue is reported as `failed`.** Billz returning zero products is indistinguishable here from a page walk that failed soft, and overwriting a good catalogue with nothing is worse. A merchant with a genuinely empty catalogue would see a permanent `failed`. Say the word and I will add a `synced`-with-zero path. |
| 4 | §2: the 36 stale tests, and whether the webhook replay guard (`webhook_replay_seen`) was lost in the views split. |
| 5 | §2: the two dead shadowed modules (`apps/integration/views.py`, `apps/dashboard/{views,serializers}.py`) — delete in their own PR. |
| 6 | Manual re-sync is unthrottled: one POST per click, each a full catalogue fetch plus a vector-store upload. If merchants lean on it, add a throttle or a "already syncing" short-circuit. |
