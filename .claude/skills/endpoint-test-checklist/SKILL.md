---
name: endpoint-test-checklist
description: >-
  Regenerate and read docs/testing/ENDPOINT_TEST_CHECKLIST.md (per-endpoint
  test-tracking) and docs/testing/ENDPOINT_PERMISSIONS.md (per-endpoint
  permission matrix) for repli-backend. Use when the user wants to see which
  endpoints have no test coverage or which permission class gates a route,
  wants either doc refreshed after routes changed, asks "what's untested",
  "what permission does X endpoint need", "refresh the checklist/matrix", or
  after the test-writer agent finishes and the table needs new rows. Never
  hand-edit the Method/Path/View columns of either file — these scripts are
  the only thing that should touch them.
---

# Endpoint Test Checklist & Permission Matrix

`docs/testing/ENDPOINT_TEST_CHECKLIST.md` is the working list the user reviews
by hand, one endpoint at a time, to confirm the tests `test-writer` (or anyone
else) wrote actually prove what they claim. It has three parts per row:
**Method/Path/View** (mechanical, from the URL resolver), **Coverage**
(heuristic — does *any* test mention this route at all), and **Reviewed**
(human judgment — never set by an agent).

## Regenerate the table

Always use the script — do not hand-write the table, and do not ask a
general-purpose agent to "just edit the markdown." The script re-walks
`django.urls.get_resolver()` (same technique as the `api-doctor` agent), so
it reflects the actual live surface, not `urls.py` read-and-guessed. Run it
after routes change, after `test-writer` finishes a batch, or whenever the
user asks for a refresh:

```bash
.venv/bin/python .claude/skills/endpoint-test-checklist/scripts/regenerate.py
```

It is safe to run repeatedly:

- Existing **Coverage** and **Reviewed** cells are carried over by matching
  `(path, view)` — a human's `[x]` or an agent's `written (...)` note is
  never silently erased.
- New routes get a fresh heuristic guess (`none` or `heuristic (test file)`)
  and an empty `[ ]`.
- Routes that vanished from the resolver move to a "Removed since last
  generation" section at the bottom instead of disappearing — tell the user
  about that section if it's non-empty so they can confirm the deletion was
  intentional before removing the row by hand.

## Reading the table for the user

When asked "what's untested" or similar, don't just dump the whole file —
filter and summarize:

```bash
grep -c '| none |' docs/testing/ENDPOINT_TEST_CHECKLIST.md
grep '| none |' docs/testing/ENDPOINT_TEST_CHECKLIST.md   # every uncovered route
grep '\[ \]' docs/testing/ENDPOINT_TEST_CHECKLIST.md      # every unreviewed row, covered or not
```

Report by app (the file is already sectioned by app with a per-app totals
line) so the user can decide where to point `test-writer` next, rather than
handing back 140 raw rows.

## The permission matrix

`docs/testing/ENDPOINT_PERMISSIONS.md` lists every endpoint's actual
`permission_classes`, translated into a plain-language access level (Public /
any authenticated user / dashboard staff / function-scoped admin / admin /
super-admin). Regenerate it the same way:

```bash
.venv/bin/python .claude/skills/endpoint-test-checklist/scripts/permissions_matrix.py
```

Views that override `get_permissions()` (different rules per HTTP method)
can't be introspected mechanically — their effective access is hand-written
in `OVERRIDE_NOTES` inside that script. **If you change a view's
`get_permissions()` logic, update `OVERRIDE_NOTES` in the same change**, or
the matrix will silently go stale and show the fallback class instead of
the real per-method split. When asked "what permission should this endpoint
use," recommend from the access-level ladder documented at the top of the
generated file — prefer the narrowest function-scoped class
(`CanManageUsers`/`CanManageFinance`/`CanModerateConversations`) that already
covers the action over reaching for `IsAdmin`.

## What this skill does not do

It does not write tests, judge whether existing tests are correct, or decide
policy on its own — that's `test-writer` for writing tests, the user's own
`[x]` for judging them, and a human call for any permission change beyond an
obvious bug (privilege escalation, a write path with no auth at all). This
skill keeps both tracking documents honest and in sync with the real URL
surface; it doesn't replace judgment about what the permission *should* be.
