# Instagram account resolution — "Integration not found for Instagram account"

**Date:** 2026-07-28
**Trigger:** Production log noise — `Integration not found for Instagram account
17841400375124995` on every inbound event for an account that exists in the database.

## Root cause

`InstagramCallbackView` stores two *different* identifiers returned by
`GET /me?fields=id,user_id,username`:

| Graph field | Column |
|---|---|
| `id` (app-scoped) | `instagram_user_id` |
| `user_id` (professional account) | `instagram_account_id` |

Every consumer of the webhook then matched **`instagram_account_id` only**. Meta puts
one or the other in `entry.id` depending on the event, so for any account where the two
values differ, `entry.id` resolved to nothing and the traffic was dropped — even though
the integration was present and correctly linked.

## Issues found

| # | Severity | Location | Issue | Fix |
|---|---|---|---|---|
| 1 | High | `views.py`, `tasks/instagram_messaging.py`, `tasks/instagram_comments.py` (10 call sites) | Single-column lookup on `instagram_account_id` dropped all traffic for accounts whose `entry.id` is the app-scoped ID | New `Integration.instagram_by_id()` matches either column and scopes to `integration_type=instagram` |
| 2 | High | `views.py:281` | Unknown account returned **404** to Meta; repeated non-2xx replies get the webhook subscription throttled and eventually disabled | Log and return 200 |
| 3 | Medium | `views.py:348` (OAuth callback) | `get_or_create` keyed on `instagram_user_id` skips its `defaults` on a match, so a row left by an earlier failed attempt kept `instagram_account_id` NULL — permanently unroutable | Explicit lookup + relink, so the identity columns always land; callback now also refuses to create a row with no `instagram_account_id` at all |
| 3b | Medium | `views.py` (OAuth callback) | `update_or_create` — the first attempt at fixing #3 — raises `MultipleObjectsReturned` (500) when `instagram_user_id` and `user` are both NULL on more than one row. The callback runs unauthenticated, so `user` is regularly NULL | Replaced with an explicit `.filter(...).first()`; the duplicate guard now excludes the row being relinked, which otherwise made the repair branch unreachable |
| 4 | Medium | `views.py:433` (deauthorize) | Matched `instagram_account_id` against the signed request's `user_id`, which is the **app-scoped** ID — so deauthorization usually found nothing and left a stale row | Uses `instagram_by_id()` |
| 5 | Medium | `views.py:143` (destroy) | Nothing ever called `DELETE /me/subscribed_apps`; Meta kept delivering events for deleted integrations forever, each one logged as unroutable | New `instagram_service.unsubscribe_webhooks()`, called on destroy |
| 6 | Low | `tasks/instagram_messaging.py` | Outbound Graph calls addressed the raw webhook `entry.id` rather than the ID stored at OAuth time | New `Integration.instagram_send_id` property (`instagram_account_id or instagram_user_id`) |
| 7 | Low | `views.py:343`, `tasks/instagram_messaging.py` | Duplicate-integration guard checked one column; `Assistant`-first lookups made the integration join implicit | Both check/resolve via `instagram_by_id()`; `Assistant` import removed as dead |

## Second round — the silent 200

A live delivery was reported as accepted but inert:

```
"POST /api/v1/integration/instagram/webhook/ HTTP/1.0" 200 93
```

93 bytes is a **unique** match for the body `{"success":true,"code":200,"message":"Webhook
ma'lumotlar muvaffaqiyatli olindi","data":null}` — the terminal fall-through, *not* the
"Integration not found" branch. Three distinct situations reached it, all silently:

| | Cause |
|---|---|
| A | `field == "comments"` but the integration didn't resolve, or had no `api_token` — the `if` had no `else` and no return, so it fell out of the loop |
| B | `changes` carried any other field (`messages`, `mentions`, `live_comments`, `story_insights`) — no handler |
| C | Neither `changes` nor `messaging` in the entry |

| # | Severity | Issue | Fix |
|---|---|---|---|
| 8 | High | The three cases above were indistinguishable from a handled event: identical status, identical body, and the only log line was a bare `"Instagram webhook data received"` | Entry shape (keys + `changes[].field`, never message content) logged on arrival; each comment-branch drop now logs its reason; the fall-through logs what it declined |
| 9 | Medium | `data.get("entry")[0]` raises `IndexError` → 500 on an entry-less payload | Guarded, acked with a warning |
| 10 | Medium | Meta batches deliveries but only `entry[0]` was ever processed — the rest vanished with no trace | Still processes only the first, but now warns with the count (full multi-entry handling left as an open item) |

## Files changed

| File | Change |
|---|---|
| `apps/integration/models.py` | `Integration.instagram_by_id()` classmethod, `instagram_send_id` property |
| `apps/integration/views.py` | All webhook lookups routed through the resolver; unknown account → 200; explicit relink-or-create in the OAuth callback; unsubscribe on destroy |
| `apps/integration/tasks/instagram_messaging.py` | Resolver-based lookup, assistant derived from the integration, outbound calls use `instagram_send_id`, dead `Assistant` import removed |
| `apps/integration/tasks/instagram_comments.py` | Resolver-based lookup; warning now names the account |
| `apps/shared/addons/instagram.py` | New fail-soft `unsubscribe_webhooks()` |
| `apps/integration/tests.py` | 16 new tests |

## Tests

Three new classes: `InstagramAccountResolutionTests` (5),
`InstagramIntegrationLifecycleTests` (6, driving the real callback view with Meta
faked) and `InstagramWebhookFallThroughTests` (5, asserting on log output). The four
resolution tests were verified to **fail** against the old single-column lookup before
the fix was restored.

```
$ .venv/bin/python manage.py test apps.integration apps.shared --keepdb
Found 111 test(s).
Ran 111 tests in 2.701s

OK
```

Two things worth knowing for future test work:

- `config/settings.py:37` calls `logging.disable(logging.CRITICAL)` under
  `manage.py test`, so `assertLogs` captures nothing. `InstagramWebhookFallThroughTests`
  lifts it per-test in `setUp` and restores it via `addCleanup`.
- The `--keepdb` test database had **leftover committed rows** from an earlier run, which
  made `Integration.objects.get(integration_type="instagram")` raise
  `MultipleObjectsReturned`. Rebuilt with `--noinput`; the new tests no longer assume a
  singleton.

**Scope of verification:** these run fully offline — `instagram_service` and `requests`
are mocked, so the resolver, callback branching and delete path are covered as *logic*.
Nothing in this change has been exercised against the live Graph API or the dev
database. `unsubscribe_webhooks()` in particular was written from the documented API
shape and never executed against Meta; it is fail-soft, so a wrong call logs a warning
rather than blocking the delete.

**Scope of verification:** these run fully offline — `instagram_service` and `requests`
are mocked, so the resolver, callback branching and delete path are covered as *logic*.
Nothing in this change has been exercised against the live Graph API or the dev
database. `unsubscribe_webhooks()` in particular was written from the documented API
shape and never executed against Meta; it is fail-soft, so a wrong call logs a warning
rather than blocking the delete.

## Open items

1. **Confirm which case the reported account hit.** The dev DB was not reachable from
   the working environment (SSH host/key live only in GitHub secrets). Run:
   ```python
   Integration.objects.filter(instagram_user_id='17841400375124995').values(
       'id', 'instagram_user_id', 'instagram_account_id')
   ```
   A hit on `instagram_user_id` confirms issue #1; a row with `instagram_account_id`
   NULL confirms issue #3; no row at all means the OAuth exchange never completed —
   see the redirect_uri item below.
2. **`redirect_uri` mismatch on the OAuth dialog.** `INSTAGRAM_REDIRECT_URI` is
   `https://app.aylo.uz/integrations/`, but the callback reads `assistant_id` from the
   query string — if the frontend appends it to the dialog's `redirect_uri`, the token
   exchange fails with *"Error validating verification code"*. `assistant_id` should
   move to the OAuth `state` parameter. **Not fixed here** — needs a frontend change.
3. **`INSTAGRAM_CLIENT_SECRET` was exposed** in an agent transcript on 2026-07-28 while
   reading `.env`. Rotate at Meta, update `/opt/aylo/.secrets/backend.env`, redeploy.
   This compounds the rotation already pending from the 2026-07-22 report.
4. **What the new log line will say.** After deploying, one delivery produces
   `Instagram webhook received for <id>: keys=[...] changes=[...]`. That single line
   settles which of A/B/C is happening. If `changes=['messages']` appears, Meta is
   delivering DMs through `changes` rather than `messaging` and the view needs a new
   branch — **this is not handled today**.
5. **Batched entries are still dropped.** Only `entry[0]` is processed; the rest are now
   counted in a warning but not handled. Worth fixing once the logs show whether Meta
   actually batches for this app.
6. **No backfill was run.** The resolver makes existing rows routable regardless of
   which column holds the ID, so none should be needed — but rows with *both* columns
   NULL are unreachable and must be re-linked through OAuth.
