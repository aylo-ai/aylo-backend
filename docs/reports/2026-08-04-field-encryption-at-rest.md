# Field encryption at rest — secrets and PII

**Date:** 2026-08-04
**Scope:** `apps/shared/addons/crypto.py`, `apps/shared/fields.py`, the six encryption
migrations, and the data-migration verification that was the outstanding step.

---

## 1. What the change does

Every credential and every piece of client PII this platform persists used to sit in
Postgres as plaintext. A stolen dump, a leaked read replica or a read-only SQL console
was enough to take over every customer's Telegram bot, replay their amoCRM session and
read every conversation transcript.

Those columns are now encrypted at the application layer with **Fernet / MultiFernet**
(AES-128-CBC + HMAC-SHA256). Values are stored as `v1:<fernet-token>`; the model fields
encrypt on write and decrypt on read, so call sites are unchanged.

| Table | Column | Field class | Why |
|---|---|---|---|
| `integration` | `api_token` | `EncryptedTextField` | Telegram bot token / IG + amoCRM + Billz access token — full account takeover |
| `integration` | `refresh_token` | `EncryptedTextField` | long-lived OAuth refresh credential |
| `integration` | `metadata` | `EncryptedJSONField` | holds the amoCRM refresh token, `client_id` and account payload |
| `integration` | `api_token_hash` | `CharField(64)` **(new)** | keyed HMAC digest so webhook dispatch can still find the row |
| `Card` | `card_token` | `EncryptedTextField` | Payme card token — chargeable |
| `messages` | `message_content` | `EncryptedTextField` | full transcripts: addresses, phone numbers, order details |
| `conversation` | `client_full_name` | `EncryptedCharField` | client PII |
| `conversation` | `client_phone_email` | `EncryptedCharField` | client PII |

Supporting pieces:

* **Version prefix `v1:`** — a value that is not shaped like a ciphertext is treated as
  legacy plaintext and returned unchanged, so the application keeps serving while the
  data migration walks the table. Deploy and migration do not have to be simultaneous.
* **`EncryptedLookupQuerySet`** — Fernet is randomised, so `WHERE api_token = 'x'` can
  never work. `Integration.objects.filter(api_token=…)` is rewritten onto
  `api_token_hash` (keyed HMAC-SHA256, indexed), which keeps every existing webhook /
  registration lookup working. Every other lookup on an encrypted column raises
  `FieldError` rather than silently returning an empty queryset.
* **Admin** — `Integration`, `Card` and `Conversation` change forms no longer render the
  credentials as editable inputs; they show `mask_secret(...)` read-only.
* **Config** — `FIELD_ENCRYPTION_KEYS` / `FIELD_ENCRYPTION_HASH_KEY`, derived from
  `SECRET_KEY` under `DEBUG`/tests, a hard `ImproperlyConfigured` otherwise.

---

## 2. Issues found and fixed

### Critical — found by rehearsing the data migration against real plaintext rows

The unit tests proved the *fields* worked. They did not prove the *data migrations*
convert a table that already contains plaintext. Rehearsing that on a scratch database
(§3) surfaced two defects, both data-affecting, both now fixed and pinned by tests.

| # | Issue | Impact | Fix |
|---|---|---|---|
| C1 | `is_encrypted()` tested only for the `v1:` prefix. `messages.message_content` and `conversation.client_full_name` hold **free-form user input**, so a customer typing `v1:...` produced a row the migration classified as already-encrypted and **skipped**. Every subsequent ORM read of that row then raised `DecryptionError`. | Permanent HTTP 500 on that conversation / integration / card, unrecoverable without manual SQL. Reproduced on all four tables. | `is_encrypted()` now also requires the remainder to be *shaped* like a Fernet token: ≥ 100 characters (the shortest possible token) of pure urlsafe-base64. |
| C2 | `backfill_hash_column()` called `decrypt()` unguarded, so one such row **aborted `integration.0045` mid-run**. Because the migration is `atomic = False`, it was left partly applied and unrecorded — the rows already walked had a digest, the rest had `NULL`. | Deploy fails; `integration.api_token_hash` is `NULL` for every row after the poison row, so **every inbound Telegram webhook for those customers stops resolving**. Observed directly in the rehearsal. | `_rewrite_table()` and `backfill_hash_column()` now catch `DecryptionError` per row, log a warning with the table and row id, and continue. One unreadable row can no longer stop the conversion of a million others. |
| C3 | Follow-up from review: with C1's first fix, a *genuine* ciphertext damaged in storage stopped being valid base64, so `is_encrypted()` returned `False` and `decrypt()` handed the **raw ciphertext back to the application as if it were the plaintext secret** — a fail-open. | Ciphertext could be pushed into an outbound Telegram/Payme call or rendered to a customer as their token. | The shape test above is deliberately *length + alphabet*, not "does it decode". A damaged token is still ≥ 100 base64-ish characters, so it is still classified as ciphertext, still reaches `Fernet.decrypt` and still raises. `Fernet` raises `InvalidToken` for malformed base64 as well as a failed HMAC, so both land in `DecryptionError`. |

#### Where the ciphertext/plaintext line now sits

Pinned case by case in `CiphertextOrPlaintextBoundaryTests`:

| Input | `is_encrypted` | `decrypt` | Correct because |
|---|---|---|---|
| intact ciphertext | `True` | plaintext | — |
| tampered in place (`ct[:-1] + 'X'`) | `True` | **raises** | HMAC catches it |
| truncated (`ct[:-1]`, `ct[:-6]`, `ct[:-12]`, `ct[:-20]`) | `True` | **raises** | still ≥ 100 base64 chars → treated as damaged ciphertext, not plaintext |
| token under a retired key | `True` | **raises** | fail closed on key misconfiguration |
| `'v1:'` | `False` | verbatim | a user can type this |
| `'v1:notbase64!!'` | `False` | verbatim | not the base64 alphabet |
| `'v1:hello world'` | `False` | verbatim | 100+ chars with no space is not prose |
| ciphertext cut in **half** | `False` | verbatim | **residual risk — see §7** |

### Medium

| # | Issue | Fix |
|---|---|---|
| M1 | The reverse (`decrypt_table_columns`) aborted on the same poison rows, so a rollback could not complete either. | Same per-row `DecryptionError` guard; the row is left as-is and logged. |
| M2 | `EncryptedCharField` on a `varchar(255)` column would truncate: a 255-character name encrypts to ~460 characters. | `EncryptedCharField.db_type()` forces `text` (already present; now covered by an executor test that asserts `information_schema` reports `text` / `NULL` max length after `assistant.0051`). |

---

## 3. Data-migration verification (the outstanding step)

Rehearsed on a throwaway database (`encmig_scratch`, since dropped) — never on
`repli_dev` or `test_repli_dev`.

**Procedure**

1. `migrate assistant 0050`, `migrate integration 0043`, `migrate payment 0020` — the
   exact pre-encryption schema.
2. Seed **plaintext** rows with raw SQL: NULL, empty string, a normal bot token, Cyrillic
   and Uzbek Latin text, emoji, a value already starting with `v1:`, values containing
   single quotes / double quotes / newlines / tabs / backslashes, a 255-character name,
   a 300 KB message body, and for `metadata`: a JSON object with Cyrillic keys, a JSON
   array, JSON `null`, `{}`, and a JSON *string* starting with `v1:`.
3. Migrate forward. Assert per row that the **raw column** is `v1:…` and that the **ORM**
   decrypts it back to the byte-exact original.
4. Run the forward `RunPython` callables twice more and diff a SHA-256 of every affected
   column.
5. Migrate backward and diff the raw columns against the seed values.

**Results (final code)**

| Step | Result |
|---|---|
| Forward, 120 assertions over 32 rows in 4 tables | `mode=encrypted checks=120 failures=0` |
| Idempotency — 2 extra forward runs | `integration / conversation / messages / "Card" unchanged: True` (byte-identical, no `UPDATE` issued) |
| Forward assertions re-run after those extra runs | `mode=encrypted checks=120 failures=0` |
| Reverse, byte-for-byte raw plaintext | `mode=plaintext checks=49 failures=0` |
| `api_token_hash` backfill | matches `hash_secret(plaintext)` for every non-empty row; `NULL`/`''` stay `NULL` |
| Column types after `0051`/`0044` | `client_full_name`/`client_phone_email` `varchar(255) → text`; `message_content`, `api_token`, `card_token` unchanged `text`; `metadata` stays `jsonb` |

**First run, before the fixes** — recorded here because it is the justification for §2:

```
mode=encrypted checks=110 failures=15
  FAIL: integration.api_token_hash[normal] None != '2cd81aa9…'      <- C2, backfill aborted
  FAIL: integration[string_v1] ORM READ FAILED: DecryptionError     <- C1
  FAIL: integration.api_token[v1_prefixed_plaintext] plaintext leaked into ciphertext
  FAIL: conversation[v1_prefixed_plaintext] ORM READ FAILED: DecryptionError
  FAIL: messages.message_content[v1_prefixed_plaintext] plaintext leaked into ciphertext
  FAIL: card[v1_prefixed_plaintext] ORM READ FAILED: DecryptionError
  … (15 total)
```

### Batching and throughput

`crypto._iter_batches` walks the table with **keyset pagination on the UUID primary key**
(`WHERE id > %s ORDER BY id LIMIT %s`, default 500) rather than `.iterator()` — it never
materialises the table, and because each page is committed separately with
`atomic = False`, an interrupted run resumes exactly where it stopped. Raw SQL is used on
purpose: the historical model already carries the encrypted field class, so going through
the ORM would encrypt on write in *both* directions and make `reverse_code` a no-op.

Measured on the scratch database with **50 008 rows** in `messages` (22 MB):

| Metric | Value |
|---|---|
| Wall clock for `assistant.0051` + `0052` | **23.7 s** (≈ 2 100 rows/s) |
| Peak RSS of the `migrate` process | **155 MB** (Django baseline ≈ 120 MB — flat, does not grow with table size) |
| Rows left in plaintext afterwards | 0 |

Writes go one row per `executemany` parameter set (psycopg2 does not pipeline these), so
throughput is round-trip bound. See §7 for the projection to production.

### DDL emitted by the schema migrations (`sqlmigrate`)

| Migration | SQL | Lock |
|---|---|---|
| `assistant.0051` | `ALTER TABLE conversation ALTER COLUMN client_full_name TYPE text` (×2) | `ACCESS EXCLUSIVE`, but `varchar(n) → text` is binary-coercible: **no table rewrite**, no index on these columns |
| `assistant.0051` | `message_content` → **`-- (no-op)`** | none — the biggest table is not touched by DDL at all |
| `integration.0044` | `ADD COLUMN api_token_hash varchar(64) NULL` + `CREATE INDEX integration_token_hash_idx` | `ADD COLUMN NULL` is metadata-only (PG 11+); the `CREATE INDEX` is **not** `CONCURRENTLY` and takes a `SHARE` lock that blocks writes to `integration` for its duration (small table — hundreds of rows) |
| `payment.0021` | **`-- (no-op)`** | none |

---

## 4. Files changed

### Owned by this task

| File | Change |
|---|---|
| `apps/shared/addons/crypto.py` | **Fixed C1/C2/C3.** Rewrote `is_encrypted()` to a length + base64-alphabet shape test with the rationale and residual risk documented; `decrypt()` docstring updated; `_rewrite_table()` and `backfill_hash_column()` now skip-and-log an undecryptable row instead of aborting. Added `re` import, `_FERNET_MIN_B64_CHARS`, `_BASE64URL_RE`. |
| `apps/shared/tests/test_crypto.py` | Added `CiphertextOrPlaintextBoundaryTests` (7 tests pinning every case in the §2 table). Reworked `test_truncated_ciphertext_fails_closed` to cover four cut lengths. Replaced the "undecryptable row" fixture (`v1:not-a-token`, now legitimately plaintext) with a real token under a foreign key, and added the legacy-`v1:`-plaintext read test. |
| `apps/shared/tests/test_encryption_migrations.py` | **New** — 10 tests, see §5. |

### Pre-existing work described for completeness (author: previous session)

| File | Change |
|---|---|
| `apps/shared/addons/crypto.py` | New module: `encrypt`/`decrypt`/`hash_secret`/`mask_secret`, `MultiFernet` key rotation, `derive_key_from_secret`, and the chunked `encrypt_table_columns` / `decrypt_table_columns` / `backfill_hash_column` migration helpers. |
| `apps/shared/fields.py` | New module: `EncryptedTextField`, `EncryptedCharField` (forces `text`), `EncryptedJSONField`, `EncryptedLookupQuerySet`. Lookups other than `isnull` raise `FieldError`. |
| `apps/integration/models.py` | `api_token`, `refresh_token`, `metadata` encrypted; `api_token_hash` + `ENCRYPTED_HASH_LOOKUPS` + `EncryptedLookupQuerySet` manager; `save()` keeps the digest in step; `assistant_for_bot_token()` helper. |
| `apps/assistant/models.py` | `Conversation.client_full_name`, `client_phone_email`, `Message.message_content` encrypted. |
| `apps/payment/models.py` | `Card.card_token` encrypted. |
| `apps/integration/admin.py`, `apps/payment/admin.py`, `apps/assistant/admin.py` | Credentials removed from the editable change forms; shown masked and read-only. |
| `config/settings.py`, `.env.example` | `FIELD_ENCRYPTION_KEYS`, `FIELD_ENCRYPTION_HASH_KEY`, dev derivation, production hard-fail. |
| `requirements.txt` | `cryptography==50.0.0`, `cffi==2.1.1`. |
| `apps/{integration,payment,assistant}/migrations/00{44,45},{21,22},{51,52}_*` | Schema + chunked, non-atomic, reversible data migrations. |
| `apps/{integration,payment,assistant}/tests_encryption.py` | 26 per-app field tests. |

---

## 5. Tests

### New: `apps/shared/tests/test_encryption_migrations.py` (10 tests)

The full `MigrationExecutor` approach **was** practical — no caveat needed.
`MigrationExecutorRoundTripTests` rewinds the real `assistant` graph to
`0050_conversation_conv_assistant_user_token_idx`, seeds plaintext with raw SQL, migrates
forward to `0052`, asserts, and migrates back — in 5.7 s. A `TransactionTestCase`
`addCleanup` re-migrates the graph to its leaf nodes before teardown, so a failure cannot
leave the `--keepdb` test database rewound (and `create_test_db` re-runs `migrate` anyway).

| Test | Covers |
|---|---|
| `MigrationExecutorRoundTripTests.test_forward_reverse_and_idempotency_over_pre_existing_plaintext` | The whole story through the real executor: 10 awkward message bodies + NULL/empty/Cyrillic conversation PII → forward → raw is ciphertext and ORM decrypts exactly → re-run changes nothing → reverse restores byte-for-byte |
| `…test_char_columns_become_text_so_ciphertext_cannot_be_truncated` | `information_schema` reports `text` / no max length after `0051`; a 255-char name round-trips |
| `DataMigrationCallableTests.test_integration_secrets_and_hash_backfill` | `0045` over NULL / empty / unicode / `v1:`-looking token / jsonb object / JSON `null` / JSON string `"v1:…"`; `api_token_hash` correct; `filter(api_token=…)` still resolves; reverse restores plaintext and `jsonb null` |
| `…test_a_row_encrypted_under_a_lost_key_is_skipped_not_fatal` | **C2 regression** — poison row is skipped and logged, healthy rows in the same batch are still converted |
| `…test_card_tokens_round_trip` | `0022` over normal / `v1:`-looking / Cyrillic / quotes+newline card tokens, both directions |
| `…test_the_table_is_walked_in_chunks_never_loaded_whole` | 7 rows at `batch_size=2` ⇒ exactly 5 `SELECT`s, every one carrying `LIMIT` and `"id" >` |
| `…test_a_conversation_with_no_pii_is_left_alone` | a table of NULLs issues zero `UPDATE`s |
| `…test_assistant_migration_handles_a_300kb_message_body` | 300 KB body forward and back |
| `…test_migrations_declare_themselves_non_atomic_and_reversible` | `atomic = False` and a `reverse_code` on all three data migrations |
| `OrmWriteAfterMigrationTests.test_mixed_plaintext_and_ciphertext_rows_all_read` | the live-rollout window: both row kinds readable before *and* after the rewrite |

### New in `apps/shared/tests/test_crypto.py` (7 tests)

`CiphertextOrPlaintextBoundaryTests` — one test per row of the §2 boundary table,
including `test_severe_damage_is_indistinguishable_from_plaintext`, which pins the
residual risk so that changing it has to be deliberate.

### Result

```
$ .venv/bin/python manage.py test apps.shared apps.integration apps.payment apps.assistant --keepdb
Using existing test database for alias 'default'...
Found 407 test(s).
System check identified no issues (0 silenced).
.......................................................................................................................................................................................................................................................................................................................................................................................................................
----------------------------------------------------------------------
Ran 407 tests in 8.117s

OK
Preserving test database for alias 'default'...
```

```
$ .venv/bin/python manage.py makemigrations --check --dry-run
No changes detected

$ .venv/bin/python manage.py check
System check identified no issues (0 silenced).
```

---

## 6. Dead code removed

`crypto.py` no longer imports `binascii` (the interim decode-based shape test is gone).
No other unused symbol was found: `grep -rn` confirms every public name in `crypto.py`
and `fields.py` has a caller (`mask_secret` → the three admin modules, `HASH_HEX_LENGTH`
→ `Integration.api_token_hash`, `decrypt_table_columns` → the three `reverse_code`s).

---

## 7. Open items — these need a human decision before production

### 7.1 Generating the production keys — exact commands

```bash
# FIELD_ENCRYPTION_KEYS — one urlsafe-base64 32-byte Fernet key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# FIELD_ENCRYPTION_HASH_KEY — any high-entropy string
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put both in the production environment (`.env` / the deployment secret store) **before**
the first deploy with `DEBUG=False` — the settings module raises `ImproperlyConfigured`
at startup without them, so a missing key is a failed boot, not silent plaintext.

> `FIELD_ENCRYPTION_HASH_KEY` is effectively **permanent**. Changing it invalidates every
> `integration.api_token_hash` and every Telegram webhook lookup until the column is
> rebuilt with `crypto.backfill_hash_column`.

### 7.2 Key rotation

`MultiFernet` — the **first** key in the comma-separated list encrypts, **every** key can
decrypt.

1. Generate a new key and **prepend** it: `FIELD_ENCRYPTION_KEYS=<new>,<old>`.
2. Redeploy. No downtime, no data rewrite: existing rows still decrypt with `<old>`, all
   new writes use `<new>`.
3. Re-encrypt the old rows before retiring `<old>` — run the data migrations' forward
   callables again. **They will not do it as written**: `is_encrypted()` short-circuits an
   already-encrypted row, which is exactly what makes the migration idempotent. A rotation
   pass needs a small separate management command (decrypt-then-encrypt every row); it
   does not exist yet. **Decision needed: build it now, or accept that keys accumulate in
   the list forever.**
4. Only after every row is confirmed re-encrypted may `<old>` be dropped from the list.
   Dropping it early is not silent — reads of the affected rows raise `DecryptionError`
   and the migration helpers log and skip them.

### 7.3 ⚠️ Backup and recovery — read this before the first deploy

**Once this ships, a database backup on its own is worthless.** `pg_dump` of
`messages`, `conversation`, `integration` and `Card` produces ciphertext. Without
`FIELD_ENCRYPTION_KEYS` there is no way — for us, for the DBA, for the hosting provider,
for anyone — to read it back. This is the point of the change, and it is also a new
single point of failure that did not exist last week.

Required before the migration runs in production:

* Store `FIELD_ENCRYPTION_KEYS` and `FIELD_ENCRYPTION_HASH_KEY` in a secret manager
  **outside** the database and **outside** the backup that contains the database.
* Keep an offline copy (sealed envelope / hardware token / two-person escrow). A key held
  only in the same cloud account as the backup does not survive that account being lost.
* **Never** commit a key. `.env.example` ships the variable names only; the settings
  module derives a throwaway key from `SECRET_KEY` under `DEBUG`/tests, which is *not* a
  secret and must never reach production.
* Add a restore drill to the runbook: restore a dump into a scratch database **and read a
  row through the ORM**. A restore that only checks row counts will pass on unreadable
  data.

### 7.4 If a key is lost

There is no recovery. Fernet is AES-128-CBC with an HMAC; there is no backdoor, no vendor
escrow, no offline crack. Concretely:

| Lost | Consequence |
|---|---|
| `FIELD_ENCRYPTION_KEYS` (all keys) | Every bot token, OAuth refresh token, Payme card token, transcript and client contact written after the migration is permanently unreadable. Customers must re-authorise every integration and re-enter every card; conversation history and leads are gone. Reads raise `DecryptionError`, so the application will 500 rather than serve garbage. |
| One key of several, still referenced by rows | Only the rows written while it was the *first* key are lost; the rest keep working. The migration helpers log and skip the unreadable rows instead of aborting (fix C2). |
| `FIELD_ENCRYPTION_HASH_KEY` | Nothing is lost, but every Telegram webhook lookup fails until `api_token_hash` is rebuilt with the new key via `crypto.backfill_hash_column`. |

### 7.5 Production rollout order for the data migration

The `messages` table is the only real concern. Deploy in **two** steps, not one.

**Step 1 — code + schema, no data rewrite.**
Deploy the application and apply only the schema migrations:

```bash
python manage.py migrate assistant   0051_encrypt_secrets_and_pii
python manage.py migrate integration 0044_encrypt_secrets_and_pii
python manage.py migrate payment     0021_encrypt_secrets_and_pii
```

Lock behaviour is in §3: `message_content` is a **no-op** (no lock on the big table),
`conversation` takes a brief `ACCESS EXCLUSIVE` with no rewrite, `integration` takes a
`SHARE` lock for the index build on a small table. Total expected impact: **sub-second,
no downtime.** After this step new writes are encrypted and old rows are still readable
as plaintext — the `v1:` prefix is what makes that mixed state legal
(`OrmWriteAfterMigrationTests` covers it).

Soak here for at least one full traffic cycle before step 2.

**Step 2 — the data rewrite.**

```bash
python manage.py migrate assistant   0052_encrypt_conversation_and_message_data
python manage.py migrate integration 0045_encrypt_integration_secret_data
python manage.py migrate payment     0022_encrypt_card_token_data
```

* `atomic = False` and 500-row keyset pages: **no long-lived table lock and no long
  transaction.** Each page is a short burst of single-row `UPDATE`s that take ordinary row
  locks; concurrent reads and writes continue throughout.
* **It is resumable and idempotent** (proven in §3). If it is interrupted — deploy
  timeout, `Ctrl-C`, OOM — re-run the same command. Rows already converted are skipped
  without an `UPDATE`.
* Run it **outside** the deploy pipeline, in `tmux`/`screen` or as a one-off job, so a
  pipeline timeout cannot kill it. Django will not have recorded `0052` until it finishes,
  so the re-run is the normal `migrate` command.
* **Capacity — needs a number from a human.** At the measured ≈ 2 100 rows/s: 1 M rows
  ≈ 8 min, 10 M rows ≈ 80 min. **What is the actual `SELECT count(*) FROM messages` in
  production?** If it is in the tens of millions, raise `batch_size` and replace
  `cursor.executemany` in `crypto._rewrite_table` with `psycopg2.extras.execute_batch`
  before running — `executemany` is one round trip per row and is the bottleneck. It was
  left as-is because it is driver-agnostic and correct; the change is worth making only
  if the table is large.
* **Disk — needs a check.** Ciphertext is roughly `4/3 × len + 100` bytes. For short
  messages that is a 3–5× growth of `message_content`; the 22 MB / 50 k-row scratch table
  grew as expected. Confirm free space is ≥ 2× the current `messages` size (the rewrite
  also produces dead tuples until `autovacuum` catches up) and consider a manual
  `VACUUM (ANALYZE) messages` afterwards.
* **Take a verified backup immediately before step 2** — and re-read §7.3 about where the
  key lives relative to that backup.

### 7.6 Residual risk accepted in the ciphertext/plaintext discriminator

A ciphertext damaged down **below 100 characters**, or mangled out of the base64 alphabet
entirely, is indistinguishable from a legacy plaintext row and is returned verbatim
(pinned by `test_severe_damage_is_indistinguishable_from_plaintext`). This is the
irreducible cost of supporting free-form user text that may itself start with `v1:`. It is
mitigated by the fact that **every encrypted column is `text`**, so Postgres cannot
truncate a value on its own — reaching that state requires manual corruption or storage
damage. If the platform ever wants zero ambiguity, the alternative is to escape a leading
`v1:` in plaintext on write and run a one-off migration to fix existing rows.
**Decision for a human: accept, or schedule the escaping change.**

### 7.7 Behavioural changes callers must know about

* `filter(api_token__icontains=…)` and any other non-`exact`, non-`isnull` lookup on an
  encrypted column now raises `FieldError` at query time, by design — a silent empty
  queryset would hide the bug. Confirm no admin `search_fields`, dashboard filter or
  reporting query still does this on `message_content`, `client_full_name`,
  `client_phone_email`, `api_token`, `refresh_token`, `metadata` or `card_token`.
* `metadata__<key>` JSON key lookups are impossible in SQL and raise; load the row and
  index into the decrypted document in Python.
* Encrypted columns cannot be indexed, sorted or grouped in SQL.
