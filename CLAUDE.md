# CLAUDE.md

Project guide for AI coding agents working in this repository. These are binding
conventions — follow them on every task.

## 1. Project overview

`repli-backend` is the Django REST backend for Repli.uz — an AI assistant / chatbot
platform integrated with Telegram and Instagram, with subscription billing.

- **Stack:** Django 5.1 · Django REST Framework · Celery · PostgreSQL · Redis ·
  Python 3.12
- **AI:** OpenAI Responses API (agentic tool loop), Vector Stores (`file_search`),
  Whisper (voice), GPT-4o vision. All AI logic lives in `apps/shared/ai_service/`.
- **Auth:** JWT (`rest_framework_simplejwt`), OTP over SMS/email, Google OAuth.
  `AUTH_USER_MODEL = "user.User"`.
- **Locale:** `LANGUAGE_CODE = "uz-uz"`, `USE_TZ = True`. User-facing strings are
  wrapped in `gettext_lazy as _` (Uzbek).

### App layout (`apps/`)
| App | Responsibility |
|---|---|
| `user` | Auth, accounts, staff, notifications, privacy/agreement docs |
| `assistant` | Assistants, conversations, messages, leads, knowledge base, follow-ups |
| `integration` | Telegram / Instagram channels, Celery tasks, broadcasts, amoCRM/Billz |
| `payment` | Subscriptions, pricing packages, cards, transactions |
| `dashboard`, `blog`, `landing` | Admin dashboard, content, marketing site |
| `shared` | Cross-cutting: `ai_service/`, `addons/` (enums, redis, telegram, verification, validations), `permissions.py`, `models.py` (`BaseModel`) |

## 2. Definition of done

A task is **not complete** until all of the following are done, in order:

1. **Implement** the change following the conventions in §3.
2. **Delete dead and unused code** touched by or adjacent to the change (§4).
3. **Write tests** covering the new behaviour and any bug being fixed (§5).
4. **Run the tests and confirm they pass** — paste the result. Never claim success
   without a green run.
5. **Write a change report** to `docs/reports/` (§6).

## 3. Coding conventions

- **API responses:** use the helpers in `shared/addons/validations.py` —
  `success_response(data, message, code)`, `error_response(...)`, and
  `raise_validation_error(...)` in serializers. Do not return bare `Response`.
- **Enums:** use `shared/addons/enums.py` (e.g. `ConversationStatuses.OPEN.value`,
  `SenderTypes.ASSISTANT.value`). Never hardcode status/type strings.
- **Permissions:** compose from `shared/permissions.py` (`IsAdmin`, `IsSuperAdmin`,
  `IsDashboardUser`, …). Remember DRF **ANDs** a permission list — use one class
  that already covers the allowed roles rather than listing several.
- **i18n:** wrap user-facing text in `_( ... )`.
- **Logging:** use module-level `logging.getLogger(__name__)` with lazy `%s`
  formatting. Never `print()` in application code, and never log secrets, OTP
  codes, tokens, or credentials.
- **External calls & handlers:** fail soft where a user turn depends on it — catch,
  log, and degrade rather than raising (see `ai_service/agent.py`, `tools.py`).

## 4. Always remove dead and unused code

As part of every change, leave the tree cleaner than you found it:

- Delete functions, classes, methods, and branches with no callers.
- Remove unused imports, variables, parameters, and settings.
- Remove commented-out code and leftover debug `print()` / `traceback` statements.
- **Verify before deleting:** `grep -rn <name> apps/` to confirm there is no
  dynamic or string-based caller.
- Prefer deletion over commenting out — git history is the archive.

## 5. Testing

- **Run tests** with the virtualenv and `--keepdb` (avoids the destroy-test-DB
  prompt that hangs non-interactive runs):
  ```bash
  .venv/bin/python manage.py test <app.path> --keepdb
  ```
- Tests run **offline** — OpenAI, Telegram, Instagram, SMS/email and Redis are
  mocked/faked. Do not make real network calls in tests. See
  `apps/shared/ai_service/tests/` and `apps/integration/tests.py` for the patterns.
- Cover the happy path, the bug being fixed (as a regression test), and failure
  degradation.
- **One import path:** every internal module is importable only as `apps.<app>.x`
  (`apps.shared.addons.redis`, `apps.user.views`). The bare `shared.x` /
  `user.views` form no longer resolves — `apps/` is not on `sys.path` and
  `INSTALLED_APPS` is fully qualified. Patch targets must use the `apps.` prefix.
  `apps/shared/tests/test_import_paths.py` enforces this.

## 6. Change reports

After finishing a task, write a dated report to
`docs/reports/YYYY-MM-DD-<topic>.md` containing:

- The issues found and the fix for each (grouped by severity for security work).
- A files-changed table.
- New tests added and the passing test result.
- Open items that need a human decision.

Keep it scannable — use tables. Example:
`docs/reports/2026-07-21-auth-and-pipeline-hardening.md`.

## 7. Git

- Commit or push **only when asked**. If on `main`, create a branch first.
- End commit messages with the required `Co-Authored-By` trailer.
