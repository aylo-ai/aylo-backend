# Change Report — Auth & AI-Pipeline Hardening

**Date:** 2026-07-21
**Branch:** `ai-pipeline-response`
**Author:** Shahzod (with Claude Code)
**Test status:** ✅ 91/91 passing — `apps.user`, `apps.shared.ai_service.tests`, `apps.integration.tests`, `apps.assistant.tests`

Two pieces of work: an **Agent/Conversation pipeline correctness fix**, then a
**user-authentication hardening pass**.

---

## Part 1 — Agent & Conversation pipeline (`apps/shared/ai_service/`)

### Bug: `/start` did not actually restart a conversation
`handle_start_command` passed `reset=True` to `get_or_create_conversation`, but the
method **ignored the argument**. A returning customer typing `/start` got the
greeting while the agent silently continued the old `previous_response_id` chain —
carrying stale context, stale instructions, and leaving a `closed` chat closed.

**Fix:** `reset=True` now calls a new `reset_conversation()` that clears the agent
chain through the agent's own `clear_chain` (so Postgres **and** the Redis cache stay
consistent) and reopens a `CLOSED` chat. An `ESCALATED` chat is left owned by the
human colleague.

| File | Change |
|---|---|
| `apps/shared/ai_service/conversation.py` | Honor `reset`; add `reset_conversation()` |
| `apps/integration/tests.py` | Regression test `test_start_command_resets_an_existing_conversation` |

**Known limitation (not changed — needs a decision):** concurrent turns on one
conversation can corrupt the chain via a lost update; currently masked by the
~2-second message debounce.

---

## Part 2 — User authentication hardening

### 🔴 Critical
| # | Issue | Fix | Files |
|---|---|---|---|
| 1 | OTP verify had **no rate limit or attempt cap** → brute-forceable | Scoped throttles (`otp_verify` 10/min, `otp_send` 5/min) + code destroyed after 5 wrong guesses | `views.py`, `verification.py`, `settings.py` |
| 2 | `/auth/register/` **required no OTP** → could mint any account | Register now gated on `check_verification_status` / `is_email_verified` | `serializers.py` |
| 3 | **Notification IDOR** — any user could edit any notification by id | `NotificationUpdateView` scoped to `request.user` (→ 404) | `views.py` |
| 4 | `verify-otp` **created users before the code was checked** | User creation moved into the view, post-verification, idempotent (`get_or_create_user`) | `serializers.py`, `views.py` |

### 🟠 High
| # | Issue | Fix |
|---|---|---|
| 5 | Google OAuth: **no CSRF `state`**, ID token **not verified** | One-time Redis `state` (10-min TTL); ID token verified with `google-auth` (`iss`/`aud`/`exp`/signature); existing email accounts linked to Google `sub` |
| 6 | **OTP codes & OAuth tokens printed** to logs | All secret-leaking `print()`s removed |

### 🟡 Medium / correctness
| # | Issue | Fix |
|---|---|---|
| 7 | `email` **not unique** (phone was) | Partial unique constraint `uniq_user_email_not_blank` (migration `0020`), ignoring NULL/blank |
| 8 | Vestigial `password` field silently dropped at register | Removed from registration serializer (Django password kept for admin/superuser) |
| 9 | Admin views used `[IsAdmin, IsSuperAdmin]` (AND → superadmin-only) | Changed to `[IsAdmin]` (admin **or** superadmin) — 4 views |
| 10 | Duplicate register → **500 IntegrityError** | Clean `400` validation error |

---

## Files changed

| File | Summary |
|---|---|
| `apps/shared/ai_service/conversation.py` | `/start` reset fix; `reset_conversation()` |
| `apps/integration/tests.py` | `/start` reset regression test |
| `apps/shared/addons/verification.py` | OTP attempt cap; removed secret logging |
| `apps/user/views.py` | Post-verification OTP flow; OAuth state + token verification; notification IDOR; admin perms |
| `apps/user/serializers.py` | OTP gate on register; duplicate dedupe; removed `password` field |
| `apps/user/models.py` | Email partial-unique constraint |
| `apps/user/tests.py` | 11 new auth tests |
| `config/settings.py` | `otp_send` / `otp_verify` throttle rates |
| `apps/user/migrations/0020_user_uniq_user_email_not_blank.py` | New — email constraint |

## New test coverage (11 tests, `apps/user/tests.py`)
OTP attempt-cap & verification · verify-otp creates-once / no-user-on-wrong-code ·
register OTP gate + duplicate 400 · notification cross-user 404 · OAuth
missing/forged `state` rejection.

---

## Open items needing a decision
1. **Migration `0020` on production** — will fail if duplicate real emails already
   exist. A dedupe data-migration should run first.
2. **JWT** — 7-day access token (`settings.py:220`) cannot be revoked once leaked.
3. **Hardcoded AMOCRM JWT** committed at `settings.py:457` — a real secret leak.
4. **Chain concurrency** (Part 1) — consider a per-conversation lock.
