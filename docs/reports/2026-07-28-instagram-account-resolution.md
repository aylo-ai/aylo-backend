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
| 3 | Medium | `views.py:348` (OAuth callback) | `get_or_create` keyed on `instagram_user_id` skips its `defaults` on a match, so a row left by an earlier failed attempt kept `instagram_account_id` NULL — permanently unroutable | `update_or_create`, so the identity columns always land; callback now also refuses to create a row with no `instagram_account_id` at all |
| 4 | Medium | `views.py:433` (deauthorize) | Matched `instagram_account_id` against the signed request's `user_id`, which is the **app-scoped** ID — so deauthorization usually found nothing and left a stale row | Uses `instagram_by_id()` |
| 5 | Medium | `views.py:143` (destroy) | Nothing ever called `DELETE /me/subscribed_apps`; Meta kept delivering events for deleted integrations forever, each one logged as unroutable | New `instagram_service.unsubscribe_webhooks()`, called on destroy |
| 6 | Low | `tasks/instagram_messaging.py` | Outbound Graph calls addressed the raw webhook `entry.id` rather than the ID stored at OAuth time | New `Integration.instagram_send_id` property (`instagram_account_id or instagram_user_id`) |
| 7 | Low | `views.py:343`, `tasks/instagram_messaging.py` | Duplicate-integration guard checked one column; `Assistant`-first lookups made the integration join implicit | Both check/resolve via `instagram_by_id()`; `Assistant` import removed as dead |

## Files changed

| File | Change |
|---|---|
| `apps/integration/models.py` | `Integration.instagram_by_id()` classmethod, `instagram_send_id` property |
| `apps/integration/views.py` | All webhook lookups routed through the resolver; unknown account → 200; `update_or_create` in the OAuth callback; unsubscribe on destroy |
| `apps/integration/tasks/instagram_messaging.py` | Resolver-based lookup, assistant derived from the integration, outbound calls use `instagram_send_id`, dead `Assistant` import removed |
| `apps/integration/tasks/instagram_comments.py` | Resolver-based lookup; warning now names the account |
| `apps/shared/addons/instagram.py` | New fail-soft `unsubscribe_webhooks()` |
| `apps/integration/tests.py` | 9 new tests |

## Tests

Two new classes: `InstagramAccountResolutionTests` (5) and
`InstagramIntegrationLifecycleTests` (4). The four resolution tests were verified to
**fail** against the old single-column lookup before the fix was restored.

```
$ .venv/bin/python manage.py test apps.integration apps.shared --keepdb
Found 104 test(s).
Ran 104 tests in 3.493s

OK
```

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
4. **No backfill was run.** The resolver makes existing rows routable regardless of
   which column holds the ID, so none should be needed — but rows with *both* columns
   NULL are unreachable and must be re-linked through OAuth.
