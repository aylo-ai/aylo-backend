"""Application-level authenticated encryption for secrets and PII at rest.

Everything sensitive that this platform persists — Telegram bot tokens,
Instagram / amoCRM / Billz OAuth tokens, Payme card tokens, conversation
transcripts and the client PII attached to them — used to sit in the database as
plaintext. A stolen dump, a leaked replica or a read-only SQL console was enough
to take over every customer's bot.

This module is the single place that turns a plaintext value into a ciphertext
blob and back. It is deliberately small; the model-level plumbing lives in
``apps/shared/fields.py``.

Design
------
* **Fernet / MultiFernet** (AES-128-CBC + HMAC-SHA256, from ``cryptography``).
  Authenticated, so a tampered ciphertext fails closed instead of decrypting to
  garbage. ``MultiFernet`` gives key rotation for free: the *first* key in
  ``settings.FIELD_ENCRYPTION_KEYS`` encrypts, every key can decrypt. Rotating
  means prepending a freshly generated key and redeploying — old rows keep
  working, new writes use the new key.
* **Version prefix.** Ciphertext is stored as ``"v1:<fernet-token>"``. The
  prefix is what makes a live rollout possible: a value *without* it is legacy
  plaintext and is returned unchanged, so the application keeps serving while
  the data migration walks the table. It also leaves room for a ``v2:`` scheme
  later without guessing at the format. The prefix alone is *not* the test —
  ``message_content`` is free-form user text and a customer can type ``v1:``
  into a chat, so :func:`is_encrypted` also requires the remainder to be
  shaped like a Fernet token. See its docstring for where the line is drawn
  and what stays ambiguous.
* **Deterministic hash for lookups.** Fernet uses a random IV, so the same
  plaintext encrypts to a different token every time and ``WHERE col = 'x'``
  can never work. Columns that are looked up by value (only
  ``Integration.api_token`` today) carry a companion HMAC-SHA256 column; see
  ``hash_secret``.

Configuration
-------------
``FIELD_ENCRYPTION_KEYS`` (list of urlsafe-base64 32-byte keys) and
``FIELD_ENCRYPTION_HASH_KEY`` are built in ``config/settings.py``. With
``DEBUG=True`` or under the test runner they are derived deterministically from
``SECRET_KEY`` so the suite runs offline; with ``DEBUG=False`` a missing
``FIELD_ENCRYPTION_KEYS`` raises ``ImproperlyConfigured`` at startup.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.core.exceptions import ImproperlyConfigured
from django.core.signals import setting_changed
from django.dispatch import receiver

logger = logging.getLogger(__name__)

#: Marks a stored value as ciphertext produced by this module. Anything without
#: it is legacy plaintext.
VERSION_PREFIX = "v1:"

#: Length of the hex digest ``hash_secret`` returns — the width of the
#: companion ``*_hash`` columns.
HASH_HEX_LENGTH = 64

#: Smallest possible Fernet token: version (1) + timestamp (8) + IV (16) +
#: one AES block (16) + HMAC-SHA256 (32) = 73 bytes, which is 100 characters of
#: padded base64. Nothing shorter can ever have come out of :func:`encrypt`.
_FERNET_MIN_B64_CHARS = 100

#: The urlsafe-base64 alphabet, anchored. A Fernet token contains nothing else
#: — no spaces, no punctuation beyond ``-``/``_``/``=``.
_BASE64URL_RE = re.compile(r"[A-Za-z0-9_-]+={0,2}\Z")

__all__ = [
    "VERSION_PREFIX",
    "HASH_HEX_LENGTH",
    "DecryptionError",
    "decrypt",
    "decrypt_table_columns",
    "encrypt",
    "encrypt_table_columns",
    "backfill_hash_column",
    "hash_secret",
    "is_encrypted",
    "mask_secret",
]


class DecryptionError(Exception):
    """A value carried the version prefix but did not authenticate.

    Raised instead of returning the raw blob: a field that silently handed back
    ciphertext would push a corrupt or tampered secret into an outbound API
    call. Fail closed.
    """


@lru_cache(maxsize=1)
def _cipher() -> MultiFernet:
    """Build the MultiFernet from settings. Cached; see ``_reset_cached_keys``."""
    from django.conf import settings

    keys = getattr(settings, "FIELD_ENCRYPTION_KEYS", None) or []
    if not keys:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEYS is empty — encrypted model fields cannot be read "
            "or written. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"`."
        )
    try:
        return MultiFernet([Fernet(key) for key in keys])
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEYS contains a value that is not a urlsafe-base64 "
            "encoded 32-byte key"
        ) from exc


@lru_cache(maxsize=1)
def _hash_key() -> bytes:
    from django.conf import settings

    key = getattr(settings, "FIELD_ENCRYPTION_HASH_KEY", None)
    if not key:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_HASH_KEY is required to look up encrypted columns"
        )
    return key.encode() if isinstance(key, str) else key


@receiver(setting_changed)
def _reset_cached_keys(sender, setting, **kwargs):  # noqa: ARG001 - signal signature
    """Drop the cached cipher when a test overrides the key settings."""
    if setting in ("FIELD_ENCRYPTION_KEYS", "FIELD_ENCRYPTION_HASH_KEY"):
        _cipher.cache_clear()
        _hash_key.cache_clear()


def derive_key_from_secret(secret: str) -> str:
    """Deterministic development key derived from ``SECRET_KEY``.

    Only used when ``DEBUG`` is on or under the test runner, so the suite (and a
    fresh checkout) works without extra configuration. It is *not* a secret —
    production must supply real keys via the environment.
    """
    digest = hashlib.sha256(f"field-encryption:{secret}".encode()).digest()
    return base64.urlsafe_b64encode(digest).decode()


def is_encrypted(value) -> bool:
    """True when ``value`` is *meant* to be a ciphertext produced by :func:`encrypt`.

    Whether it still authenticates is :func:`decrypt`'s business — this only
    decides "ciphertext or legacy plaintext", and it has to get that call right
    in both directions:

    * **Not prefix-only.** ``Message.message_content`` and
      ``Conversation.client_full_name`` hold free-form user input, so a
      customer can perfectly well send ``"v1:hello"``. Treating the prefix
      alone as proof made the data migration skip such a row and then made
      every read of it raise :class:`DecryptionError` — a permanent 500 on that
      conversation.
    * **Not "does it decode".** A real ciphertext damaged in storage stops
      being valid base64, and returning it verbatim would hand ciphertext to
      the application as though it were a plaintext secret. Damage must fail
      loud.

    The line drawn between the two is the *shape* of the remainder: at least
    :data:`_FERNET_MIN_B64_CHARS` characters (no Fernet token can be shorter)
    drawn only from the urlsafe-base64 alphabet. Anything :func:`encrypt` ever
    produced passes, whole or damaged; human text does not, because 100+
    characters without a space or a punctuation mark is not prose.

    Residual ambiguity — a token damaged down below 100 characters, or one
    mangled into non-base64 — is read as plaintext. It is genuinely
    indistinguishable from a legacy row, and the columns are all ``text``, so
    the database cannot truncate a value on its own.
    """
    if not isinstance(value, str) or not value.startswith(VERSION_PREFIX):
        return False
    body = value[len(VERSION_PREFIX):]
    return len(body) >= _FERNET_MIN_B64_CHARS and _BASE64URL_RE.match(body) is not None


def encrypt(value):
    """Encrypt ``value`` and return ``"v1:<token>"``.

    ``None`` and ``""`` pass through untouched — there is nothing to hide and
    keeping them lets ``NULL`` / empty stay queryable.
    """
    if value is None or value == "":
        return value
    if not isinstance(value, str):
        value = str(value)
    return VERSION_PREFIX + _cipher().encrypt(value.encode()).decode()


def decrypt(value):
    """Decrypt a value produced by :func:`encrypt`.

    A value that is not shaped like a ciphertext (see :func:`is_encrypted`) is
    legacy plaintext written before this column was encrypted and is returned
    unchanged — that is what keeps the application serving while the data
    migration runs.

    :raises DecryptionError: the value is shaped like a ciphertext but does not
        authenticate — wrong key, damaged column, tampered row. ``Fernet``
        raises ``InvalidToken`` for malformed base64 as well as for a failed
        HMAC, so both land here.
    """
    if not is_encrypted(value):
        return value
    try:
        return _cipher().decrypt(value[len(VERSION_PREFIX):].encode()).decode()
    except InvalidToken as exc:
        # Never log the token itself.
        logger.error("Failed to decrypt a stored value: token did not authenticate")
        raise DecryptionError(
            "stored value did not authenticate — wrong FIELD_ENCRYPTION_KEYS or tampered row"
        ) from exc


def hash_secret(value) -> str | None:
    """Deterministic HMAC-SHA256 hex digest used to look a secret up by value.

    Fernet is randomised, so an encrypted column cannot be searched. Columns
    that must be searchable (``Integration.api_token``) carry this digest in a
    companion ``*_hash`` column. Keyed with ``FIELD_ENCRYPTION_HASH_KEY`` so a
    dump alone does not allow offline brute-forcing of short tokens.
    """
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        value = str(value)
    return hmac.new(_hash_key(), value.encode(), hashlib.sha256).hexdigest()


def mask_secret(value, keep: int = 4) -> str:
    """Render a secret safe for logs: ``"***abcd"``.

    Reveals at most the last ``keep`` characters and never the length, so a
    short token cannot be reconstructed from repeated log lines.
    """
    if not value:
        return "***"
    text = str(value)
    if len(text) <= keep:
        return "***"
    return f"***{text[-keep:]}"


# --------------------------------------------------------------------------
# Data-migration helpers
#
# Chunked, keyset-paginated column rewrites. `messages.message_content` holds
# every conversation turn ever sent, so nothing here may load a whole table:
# rows are walked in batches of `batch_size` ordered by the UUID primary key,
# which every affected table inherits from `shared.models.BaseModel`.
#
# Raw SQL on purpose. Inside a migration the historical model already carries
# the encrypted field class, so going through the ORM would encrypt on write in
# *both* directions and make `reverse_code` a no-op.
# --------------------------------------------------------------------------

_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def _iter_batches(connection, table, selected, batch_size):
    quote = connection.ops.quote_name
    sql = (
        f"SELECT {quote('id')}, {', '.join(selected)} FROM {quote(table)} "
        f"WHERE {quote('id')} > %s ORDER BY {quote('id')} LIMIT %s"
    )
    last_id = _ZERO_UUID
    while True:
        with connection.cursor() as cursor:
            cursor.execute(sql, [last_id, batch_size])
            rows = cursor.fetchall()
        if not rows:
            return
        yield rows
        last_id = str(rows[-1][0])


def _rewrite_table(connection, table, text_columns, json_columns, text_op, json_op, batch_size):
    text_columns = list(text_columns)
    json_columns = list(json_columns)
    if not text_columns and not json_columns:
        return

    quote = connection.ops.quote_name
    # jsonb is read as ``::text`` so the payload is handled as raw JSON text no
    # matter which adapter is registered on the connection.
    selected = [quote(column) for column in text_columns]
    selected += [f"{quote(column)}::text" for column in json_columns]
    assignments = [f"{quote(column)} = %s" for column in text_columns]
    assignments += [f"{quote(column)} = %s::jsonb" for column in json_columns]
    update_sql = (
        f"UPDATE {quote(table)} SET {', '.join(assignments)} WHERE {quote('id')} = %s"
    )

    for rows in _iter_batches(connection, table, selected, batch_size):
        params = []
        for row in rows:
            pk, values = row[0], list(row[1:])
            split = len(text_columns)
            try:
                rewritten = [text_op(value) for value in values[:split]]
                rewritten += [json_op(value) for value in values[split:]]
            except DecryptionError:
                # One unreadable row (a key retired while its rows were still
                # encrypted with it) must not abort the whole rewrite and leave
                # a half-migrated table behind. Leave it alone and keep going;
                # the operator has the row id and can restore the key.
                logger.warning(
                    "%s row %s left unchanged: value did not decrypt with the "
                    "configured FIELD_ENCRYPTION_KEYS",
                    table,
                    pk,
                )
                continue
            if rewritten != values:
                params.append([*rewritten, pk])
        if params:
            with connection.cursor() as cursor:
                cursor.executemany(update_sql, params)


def _encrypt_text(value):
    """Encrypt unless the row was already rewritten — the migration is re-runnable."""
    return value if is_encrypted(value) else encrypt(value)


def _encrypt_json(raw):
    """``raw`` is the jsonb document rendered as text; return its replacement."""
    if raw is None:
        return None
    if is_encrypted(json.loads(raw)):
        return raw
    return json.dumps(encrypt(raw))


def _decrypt_json(raw):
    if raw is None:
        return None
    decoded = json.loads(raw)
    if not is_encrypted(decoded):
        return raw
    return decrypt(decoded)


def encrypt_table_columns(connection, table, columns=(), json_columns=(), batch_size=500):
    """Encrypt plaintext rows in ``table`` in batches. Safe to re-run."""
    _rewrite_table(connection, table, columns, json_columns, _encrypt_text, _encrypt_json, batch_size)


def decrypt_table_columns(connection, table, columns=(), json_columns=(), batch_size=500):
    """Reverse of :func:`encrypt_table_columns` — restores plaintext in batches."""
    _rewrite_table(connection, table, columns, json_columns, decrypt, _decrypt_json, batch_size)


def backfill_hash_column(connection, table, source_column, hash_column, batch_size=500):
    """Populate ``hash_column`` from ``source_column`` for every existing row.

    ``source_column`` may hold either plaintext or ciphertext — :func:`decrypt`
    passes plaintext through — so this works before or after encryption.
    """
    quote = connection.ops.quote_name
    update_sql = (
        f"UPDATE {quote(table)} SET {quote(hash_column)} = %s WHERE {quote('id')} = %s"
    )
    selected = [quote(source_column), quote(hash_column)]
    for rows in _iter_batches(connection, table, selected, batch_size):
        params = []
        for pk, value, existing in rows:
            try:
                digest = hash_secret(decrypt(value))
            except DecryptionError:
                # Same reasoning as `_rewrite_table`: skip the row rather than
                # abort the migration. The consequence is scoped — that one
                # secret stays unsearchable until the key is restored.
                logger.warning(
                    "%s row %s: %s did not decrypt, %s not backfilled",
                    table,
                    pk,
                    source_column,
                    hash_column,
                )
                continue
            if digest != existing:
                params.append([digest, pk])
        if params:
            with connection.cursor() as cursor:
                cursor.executemany(update_sql, params)
