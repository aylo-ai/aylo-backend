# Auth and access-control hardening — 2026-08-04

Two-part change. Part 1 (auth surface, `apps/user` + `apps/shared`) was started by
an earlier session; Part 2 (tenant isolation in `apps/assistant`) completes it,
re-audits Part 1's unverified edits, and puts the whole `/api/v1/chat/…` surface
under test.

The `apps/assistant` edits from Part 1 shipped with **zero** IDOR tests. This
report treats them as unverified-until-proven and records the audit result for
each one, plus the two live defects that audit turned up.

---

## 1. Findings

### Critical

| # | Finding | Fix | Where |
|---|---|---|---|
| C1 | `UserRoles.STAFF` was in `DASHBOARD_ROLES`, so every `IsDashboardUser` endpoint (`/api/v1/dashboard/…` — all users, all assistants, all conversations, all transactions, platform-wide) accepted a staff token. Any customer can mint a staff account through `/api/v1/user/add-staff/`, which hands back a ready-to-use token pair. That is self-service escalation from one tenant to the whole platform. | `STAFF` removed from `DASHBOARD_ROLES`, with a comment explaining why it must never return. | `apps/shared/permissions.py` |
| C2 | `LogoutView` blacklisted whatever refresh token it was handed without checking whose it was. Any authenticated caller holding someone else's refresh token could revoke it at will. | Compare `token["user_id"]` against `request.user.id` before `blacklist()`. | `apps/user/views.py` |

### High

| # | Finding | Fix | Where |
|---|---|---|---|
| H1 | `AssistantFileUpload.assistant` was writable and `AssistantFileUploadRetrieveView.update()` passes the body straight to `ModelSerializer.update()`. `PATCH /api/v1/chat/assistant-files/<id>/ {"assistant": "<victim id>"}` re-filed the caller's document under a **foreign tenant's** assistant — and the next `DELETE` then called `knowledge_base.delete_file(victim.vector_id, …)` against the victim's OpenAI vector store. **Found in this session; the Part 1 sweep missed it.** | `read_only_fields = ["assistant", …]` on `AssistantFileUploadSerializer` and `UpdateFileUploadSerializer`; both `create()` paths already read the assistant off the view-supplied context. | `apps/assistant/serializers.py` |
| H2 | `Assistant.user`, `Conversation.assistant`, `Message.conversation` and `Lead.assistant` were all writable. Each let a request body override the URL and cross the tenant boundary the view had just checked. | `read_only_fields` on all four. | `apps/assistant/serializers.py` |
| H3 | `GoogleAuthCallbackView` had no CSRF defence on the OAuth callback and echoed the raw ID-token verification error back to the caller. | One-time Redis `state` issued by `GoogleLoginView` and consumed by the callback; the verification failure is logged, not echoed. | `apps/user/views.py` |
| H4 | OTP codes were compared with `==` (timing oracle) and had no per-identifier rate limit — only per-IP scopes, which an attacker resets by rotating source addresses and which let one NAT'd user lock out everyone behind that address. | `hmac.compare_digest` in `_codes_match()`; new `OtpSendIdentifierThrottle` / `OtpVerifyIdentifierThrottle` keyed on the phone/email, plus a 60s email resend cooldown. | `apps/shared/addons/verification.py`, `apps/user/services/throttles.py`, `config/settings.py` |
| H5 | Access tokens lived 7 days, refresh tokens 30. Nothing can revoke an access token, so its lifetime *is* the window an attacker keeps a stolen one. | 60 min / 14 days, both overridable by env var. | `config/settings.py` |

### Medium

| # | Finding | Fix | Where |
|---|---|---|---|
| M1 | `FollowUpStageListCreateView.create()` resolved the assistant with a hand-rolled `Q(user=request.user) \| Q(user=request.user.created_by)`. `created_by` is `None` for every ordinary customer, so the second leg collapsed to `user IS NULL` and matched **every ownerless assistant on the platform** — any authenticated user could attach follow-up stages (i.e. outbound messages sent on someone else's behalf) to one. `Assistant.user` is nullable, so these rows exist. The rest of the module already used `owned_assistants()` precisely to avoid this; this one call site was left behind. **Found in this session.** | Use `owned_assistants(request.user)`. | `apps/assistant/views.py` |
| M2 | `LoginRefreshSerializer` minted fresh access tokens for deactivated accounts. | `User.objects.filter(id=…, is_active=True)`. | `apps/user/serializers.py` |
| M3 | `UpdateProfileSerializer` exposed `phone_number` as writable. `update()` never wrote it, but its presence attached the model's uniqueness check — PATCHing an arbitrary number answered "already registered", a free account-enumeration oracle. | `read_only_fields = ["id", "phone_number"]`. | `apps/user/serializers.py` |
| M4 | `NotificationSerializer` let a recipient rewrite the title/content/type of a notice the platform sent them. | Only `is_read` stays writable. | `apps/user/serializers.py` |
| M5 | An expired ngrok tunnel host sat in `CORS_ALLOWED_ORIGINS` with `CORS_ALLOW_CREDENTIALS` on. `*.ngrok-free.app` subdomains are recycled to whoever claims them next. | Removed from `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS`. | `config/settings.py` |
| M6 | No production security headers. | `SECURE_HSTS_SECONDS`, `SESSION_COOKIE_HTTPONLY`, `CSRF_COOKIE_HTTPONLY`, `X_FRAME_OPTIONS=DENY`, `SECURE_REFERRER_POLICY`, `SECURE_CROSS_ORIGIN_OPENER_POLICY` under `if not DEBUG:`. | `config/settings.py` |

### Low / hygiene

| # | Finding | Fix |
|---|---|---|
| L1 | Dead permission classes: `IsManager`, `IsSupportAgent`, `CanModerateConversations`, `MANAGEMENT_ROLES`. | Deleted — see §3 for the verification that this was dead code and not a weakened check. |
| L2 | Dead serializers/views: `SettingsSerializer` + `SettingsListCreateView`/`SettingsRetrieveView`, `AssistantFileGoogleDocSerializer`, `AddUserSerializer`, `DeleteCompanyUsersSerializer`, `clear_verified_flag()`, `send_sms_text()`, a commented-out `AssistantFileGoogleDocView` and its commented-out URL. | Deleted. |
| L3 | `SendCodeView`, `VerifyCodeView`, `UserRegisterView`, `GoogleLoginView`, `GoogleAuthCallbackView` relied on the *absence* of `DEFAULT_PERMISSION_CLASSES` to be public. | Explicit `permission_classes = [permissions.AllowAny]` + a docstring saying why each is public. Behaviour unchanged; the intent is now auditable. |

---

## 2. Re-audit of every authenticated `apps/assistant` viewset

The hunted pattern: `get_queryset()` returning `Model.objects.all()` while the
view looks the object up by URL pk. Verdicts below are from reading the code and
are now pinned by the tests in §4 — every row is exercised for list, retrieve,
update **and delete**.

| View | Scoping mechanism | Verdict |
|---|---|---|
| `AssistantListCreateView` | `owned_assistants()` | OK |
| `AssistantRetrieveView` | `owned_assistants()`; delete additionally refuses staff | OK |
| `AssistantTokenStatsView` | `owned_assistants()` | OK |
| `ConversationListCreateView` | `assistant__in=owned_assistants()` + explicit check on create | OK |
| `ConversationRetrieveView` | `get_object()` filters on `assistant__in=owned_assistants()` | OK |
| `MessageListCreateView` | `conversation__assistant__in=…` + explicit check on create | OK |
| `MessageRetrieveView` | `conversation__assistant__in=…` | OK |
| `ConversationMessagesListView` | `conversation__assistant__in=…` | OK |
| `MessageBulkReadView` | conversation ownership checked, and the UPDATE is re-scoped by `conversation__id` — nested route, own parent, foreign child ids in the body cannot escape | OK |
| `AssistantFileUploadListCreateView` | `assistant__in=owned_assistants()` | OK |
| `AssistantFileUploadUpdateView` | `owned_assistants().get(id=…)` | OK |
| `AssistantFileUploadRetrieveView` | `assistant__in=owned_assistants()` | queryset OK; **serializer was not — H1** |
| `LeadListCreateView` / `LeadRetrieveView` | `assistant__in=owned_assistants()` | OK |
| `ExportLeadsView` | `owned_assistants().filter(id=…).exists()` | OK |
| `FollowUpConfigView` | `owned_assistants()` | OK |
| `FollowUpStageListCreateView` | list scoped; **create was not — M1** | Fixed |
| `FollowUpStageDetailView` | `config__assistant__in=owned_assistants()` | OK |
| `FollowUpLogListView` | `conversation__assistant__in=owned_assistants()` | OK |
| `PromptTemplateListView` | Global catalogue, no tenant data | OK by design |

**Over-scoping check.** The Part 1 edits could plausibly have broken legitimate
access — `AssistantFileUploadRetrieveView` was widened from
`assistant__user=request.user` to `owned_assistants()` (which admits a customer's
staff), and `MessageSerializer.validate` lost its body fallback for
`conversation`. `OwnerAccessTests` and `StaffTenantAccessTests` (§4) assert the
owner and the owner's staff still get a full CRUD path on every resource. Nothing
was over-scoped.

**Media / file access.** `AssistantFileUpload.file` and `Message.audio_file` are
*not* served by Django in production (`config/urls.py` only mounts `static()`
under `DEBUG`). They live on S3 via `S3Boto3Storage`, and `AWS_QUERYSTRING_AUTH`
is left at its default of `True`, so `file.url` is a signed, expiring URL rather
than a bare object path. That is a real control, not an unguessable URL — **but
only if the bucket and the `AWS_S3_CUSTOM_DOMAIN` CDN in front of it are not
public-read**, which cannot be verified from this repo. Object keys are fully
predictable (`assistant/<assistant-uuid>/files/<original-filename>`), so a
public bucket is directly enumerable from any assistant id the caller has seen.
Raised as open item O3.

---

## 3. `apps/shared/permissions.py` lost 51 lines — genuine dead code?

**Yes.** Verified by grep across the whole tree:

```
$ grep -rn "MANAGEMENT_ROLES\|IsManager\|IsSupportAgent\|CanModerateConversations" apps/ config/
(no matches)
```

Same for the other Part 1 deletions:

```
$ grep -rn "AddUserSerializer\|DeleteCompanyUsersSerializer\|clear_verified_flag\|send_sms_text" apps/ config/
(no matches)

$ grep -rn "SettingsSerializer\|SettingsListCreateView\|SettingsRetrieveView\|AssistantFileGoogleDocSerializer" apps/ config/
(no matches)
```

None of the removed classes was ever referenced by a `permission_classes` list,
a string, or a dynamic lookup, so no endpoint lost a check. The only *behavioural*
change in that file is C1 — removing `STAFF` from `DASHBOARD_ROLES`, which
**tightens** access and is pinned by `DashboardRoleSeparationTests` in
`apps/user/tests.py`.

Every surviving consumer of the file still resolves: `IsAdmin`, `IsSuperAdmin`,
`IsDashboardUser`, `IsCustomer`, `IsAdminOrCustomer`, `CanManageUsers`,
`CanManageFinance`, `DASHBOARD_ROLES`, `ADMIN_ROLES` — all still defined, all
still imported successfully (the 300-test run below imports every view module).

One leftover from L2 that is **not** in this session's file ownership:
`process_google_doc()` in `apps/assistant/services/google.py` is now unreferenced
after `AssistantFileGoogleDocSerializer` was deleted. Left in place; see open
item O4.

---

## 4. Files changed

| File | Change |
|---|---|
| `apps/shared/permissions.py` | C1 (STAFF out of `DASHBOARD_ROLES`), L1 (dead classes deleted) |
| `apps/shared/addons/verification.py` | H4 (constant-time compare, resend cooldown), L2 |
| `apps/user/views.py` | C2, H3, L3 |
| `apps/user/serializers.py` | M2, M3, M4, L2 |
| `apps/user/services/throttles.py` | **New** — per-identifier OTP throttles (H4) |
| `apps/user/tests.py` | +454 lines, 15 new auth test classes (Part 1) |
| `apps/shared/tests/test_security_settings.py` | **New** — asserts the JWT lifetimes, CORS list and header block |
| `apps/assistant/views.py` | **M1 (this session)**; Part 1: dead `Settings*` views deleted, file-detail scoping unified, encrypted columns dropped from `search_fields` |
| `apps/assistant/serializers.py` | **H1 (this session)**; Part 1: H2 `read_only_fields`, dead serializers deleted, `_`-shadowing 500 fixed |
| `apps/assistant/urls.py` | Commented-out google-doc route deleted |
| `apps/assistant/tests.py` | **+789 lines, 4 new test classes, 63 new tests (this session)** |
| `config/settings.py` | H4 throttle scopes, H5 JWT lifetimes, M5 CORS/CSRF, M6 header block |

No model, migration or admin file was touched. `makemigrations --check --dry-run`
reports **No changes detected**.

---

## 5. Tests added this session

`apps/assistant/tests.py` went from 29 to 92 tests (+63). Four new classes, all
offline (OpenAI, Redis and S3 mocked; uploads use `InMemoryStorage`):

| Class | Tests | Covers |
|---|---|---|
| `TenantIsolationTests` | 39 | For every scoped resource, with tenant B authenticated against tenant A's object: list excludes it, retrieve/update/**delete** all 404, nested creates 404. Plus the two regressions: ownerless-assistant follow-up create, and `delete_file`/`delete_store` never firing on a 404. |
| `MassAssignmentTests` | 10 | Authenticated as the legitimate owner, PATCH/POST a cross-tenant `user` / `assistant` / `conversation` / `config` — each is ignored, the object stays put. |
| `OwnerAccessTests` | 10 | The positive half: the owner can still list, read, update, delete, bulk-read and export every resource. Guards against over-scoping. |
| `StaffTenantAccessTests` | 4 | A customer's staff account reaches exactly that customer's tenant, and still cannot delete an assistant. |

Deliberate choices:

- **404, never 403** on foreign objects — a 403 confirms the id exists.
- **Delete is asserted separately for every resource.** Partial fixes that scope
  only list/retrieve are the common failure mode.
- **Nested-route laundering is tested both directions**: foreign parent (→404)
  and *own* parent with a foreign child id in the body
  (`test_bulk_read_through_an_owned_conversation_cannot_reach_foreign_messages`).
- `Message.message_content` and `Conversation.client_full_name` /
  `client_phone_email` are encrypted at rest, so no test filters, orders or
  `.get()`s on them by plaintext — comparisons go through `refresh_from_db()`.

### Both new tests were confirmed to fail against the unfixed code

Reverting only the H1 and M1 fixes and re-running:

```
FAIL: test_follow_up_stage_create_on_an_ownerless_assistant_is_404
AssertionError: 201 != 404

FAIL: test_knowledge_base_file_cannot_be_moved_to_another_tenant
AssertionError: <Assistant: None - Victim Bot> != <Assistant: None - Intruder Bot>

Ran 2 tests in 0.059s
FAILED (failures=2)
```

They are regression tests, not tautologies.

---

## 6. Test run

### Full mandated scope — 3 pre-existing failures outside this change

```
$ .venv/bin/python manage.py test apps.user apps.assistant apps.shared apps.dashboard --keepdb
Using existing test database for alias 'default'...
Found 300 test(s).
System check identified no issues (0 silenced).
.................................................................................................F.......F...........F..........................
======================================================================
FAIL: test_decryption_failure_never_logs_the_token (apps.shared.tests.test_crypto.EncryptDecryptTests.test_decryption_failure_never_logs_the_token)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/shahzod/mywork/aylo-backend/apps/shared/tests/test_crypto.py", line 101, in test_decryption_failure_never_logs_the_token
    with self.assertRaises(crypto.DecryptionError):
AssertionError: DecryptionError not raised

======================================================================
FAIL: test_truncated_ciphertext_fails_closed (apps.shared.tests.test_crypto.EncryptDecryptTests.test_truncated_ciphertext_fails_closed)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/shahzod/mywork/aylo-backend/apps/shared/tests/test_crypto.py", line 91, in test_truncated_ciphertext_fails_closed
    with self.assertRaises(crypto.DecryptionError):
AssertionError: DecryptionError not raised

======================================================================
FAIL: test_undecryptable_row_raises_instead_of_returning_ciphertext (apps.shared.tests.test_crypto.EncryptedFieldTests.test_undecryptable_row_raises_instead_of_returning_ciphertext)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/shahzod/mywork/aylo-backend/apps/shared/tests/test_crypto.py", line 244, in test_undecryptable_row_raises_instead_of_returning_ciphertext
    with self.assertRaises(crypto.DecryptionError):
AssertionError: DecryptionError not raised

----------------------------------------------------------------------
Ran 300 tests in 1.831s

FAILED (failures=3)
Preserving test database for alias 'default'...
```

**All three failures are in `apps/shared/tests/test_crypto.py`, exercising
`apps/shared/addons/crypto.py` and `apps/shared/fields.py` — the field-encryption
work, which was in flight in a parallel session and is outside this change's
scope.** They were failing before this session's first edit and are untouched by
it: nothing here imports `crypto`. Open item O5.

### Everything else — green

```
$ .venv/bin/python manage.py test apps.user apps.assistant apps.dashboard \
    apps.shared.ai_service apps.shared.tests.test_deployment_compose \
    apps.shared.tests.test_enums apps.shared.tests.test_http \
    apps.shared.tests.test_import_paths apps.shared.tests.test_security_settings \
    apps.shared.tests.test_telegram_webhook_logging --keepdb
Using existing test database for alias 'default'...
Found 250 test(s).
System check identified no issues (0 silenced).
..........................................................................................................................................................................................................................................................
----------------------------------------------------------------------
Ran 250 tests in 1.837s

OK
Preserving test database for alias 'default'...
```

### `apps.assistant` alone

(99 = the 92 in `tests.py` plus the 7 in the parallel session's
`tests_encryption.py`.)

```
$ .venv/bin/python manage.py test apps.assistant --keepdb
Using existing test database for alias 'default'...
Found 99 test(s).
System check identified no issues (0 silenced).
...................................................................................................
----------------------------------------------------------------------
Ran 99 tests in 0.964s

OK
Preserving test database for alias 'default'...
```

### Migrations

```
$ .venv/bin/python manage.py makemigrations --check --dry-run
No changes detected
```

---

## 7. `manage.py check --deploy`

Run with `DEBUG=False` and the env vars the settings module now demands:

```
$ DEBUG=False FIELD_ENCRYPTION_KEYS=<generated> FIELD_ENCRYPTION_HASH_KEY=<set> \
  AMOCRM_CLIENT_ID=x AMOCRM_SECRET_KEY=x .venv/bin/python manage.py check --deploy
...
?: (security.W008) Your SECURE_SSL_REDIRECT setting is not set to True. ...
?: (security.W009) Your SECRET_KEY has less than 50 characters, less than 5 unique
   characters, or it's prefixed with 'django-insecure-' ...

System check identified 100 issues (0 silenced).
```

**Two** security warnings remain. The other 98 issues are all
`drf_spectacular.W002` ("unable to guess serializer" on plain `APIView`s) —
schema-generation noise, not security.

| Warning | Status | Why |
|---|---|---|
| `security.W008` `SECURE_SSL_REDIRECT` | **Accepted for now — needs a human (O1)** | Deliberately not set. The committed vhost `deployment/nginx/api.aylo.uz.conf` terminates on `:80` only, so `X-Forwarded-Proto` is `http` and Django would answer every request with a redirect to itself — an instant outage. Must be enabled in the same change that adds the TLS server block. |
| `security.W009` `SECRET_KEY` | **Local artifact, not a code defect** | Fires because the developer `.env` in this checkout holds a 29-char `django-insecure-…` key. In production `SECRET_KEY` comes from the environment and settings already hard-fail at startup if it is missing when `DEBUG` is off. There is, however, no guard against a *weak* value — see O2. |

Warnings that used to fire and no longer do, thanks to the `if not DEBUG:` block:
`W004` (HSTS), `W006`/`W019` (`X_FRAME_OPTIONS`), `W012`/`W016` (cookie flags),
`W018` (`DEBUG`).

---

## 8. Open items for a human

| # | Item | Why it needs a decision |
|---|---|---|
| **O1** | Enable `SECURE_SSL_REDIRECT` + add the TLS server block to `deployment/nginx/api.aylo.uz.conf`. | Infrastructure change. Turning the setting on before nginx terminates TLS and forwards `X-Forwarded-Proto: https` takes the API down. |
| **O2** | Reject a weak `SECRET_KEY` at startup when `DEBUG` is off (length ≥ 50 and no `django-insecure-` prefix). | The guard belongs in the `SECRET_KEY` block of `config/settings.py`, which is outside this session's edit scope. It is a two-line change; someone should confirm the production key already satisfies it before the guard is added, or the next deploy will refuse to boot. |
| **O3** | Confirm the S3 bucket and the `AWS_S3_CUSTOM_DOMAIN` CDN are **not** public-read. | Access control for knowledge-base uploads and voice notes rests entirely on S3 presigned URLs. Object keys are predictable (`assistant/<uuid>/files/<filename>`), so a public bucket is enumerable from any assistant id. Note the constraint: `knowledge_base.add_file()` hands the URL to OpenAI to fetch, so the bucket cannot simply be locked down — the presigned URL must stay valid long enough for ingestion. If the CDN serves objects unsigned, the fix is a randomised key prefix (a `models.py` change, owned elsewhere) plus a CDN policy change. |
| **O4** | Delete `process_google_doc()` and the rest of `apps/assistant/services/google.py`. | Now unreferenced after `AssistantFileGoogleDocSerializer` was removed. `apps/assistant/services/` was outside this session's file ownership, so it was left alone rather than risk a conflict with a parallel session. |
| **O5** | The 3 `test_crypto.py` failures. | Owned by the parallel field-encryption work: `crypto.decrypt()` is not raising `DecryptionError` on a truncated/undecryptable ciphertext, so encrypted columns currently fail **open** rather than closed. That is a security property in its own right and should be resolved before either change ships. |
| **O6** | `ACCESS_TOKEN_LIFETIME` dropped from 7 days to 60 minutes (H5). | Behavioural change for clients. Anything that does not call `/api/v1/user/auth/login/refresh/` on a 401 will start logging users out hourly. Mobile/web clients need checking, or the deploy needs `ACCESS_TOKEN_LIFETIME_MINUTES` set higher as a transitional measure. |
| **O7** | Message and conversation search no longer matches transcript text or client PII. | `message_content`, `client_full_name` and `client_phone_email` are encrypted at rest, so they were removed from `search_fields` in `apps/assistant/views.py` and `apps/dashboard/views.py`. Searching them again needs a blind-index or a dedicated search store — a product decision, not a fix. |
