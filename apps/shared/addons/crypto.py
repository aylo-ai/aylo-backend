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

VERSION_PREFIX = "v1:"

HASH_HEX_LENGTH = 64

_FERNET_MIN_B64_CHARS = 100

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
    pass


@lru_cache(maxsize=1)
def _cipher() -> MultiFernet:
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
    if setting in ("FIELD_ENCRYPTION_KEYS", "FIELD_ENCRYPTION_HASH_KEY"):
        _cipher.cache_clear()
        _hash_key.cache_clear()


def derive_key_from_secret(secret: str) -> str:
    digest = hashlib.sha256(f"field-encryption:{secret}".encode()).digest()
    return base64.urlsafe_b64encode(digest).decode()


def is_encrypted(value) -> bool:
    if not isinstance(value, str) or not value.startswith(VERSION_PREFIX):
        return False
    body = value[len(VERSION_PREFIX):]
    return len(body) >= _FERNET_MIN_B64_CHARS and _BASE64URL_RE.match(body) is not None


def encrypt(value):
    if value is None or value == "":
        return value
    if not isinstance(value, str):
        value = str(value)
    return VERSION_PREFIX + _cipher().encrypt(value.encode()).decode()


def decrypt(value):
    if not is_encrypted(value):
        return value
    try:
        return _cipher().decrypt(value[len(VERSION_PREFIX):].encode()).decode()
    except InvalidToken as exc:
        logger.error("Failed to decrypt a stored value: token did not authenticate")
        raise DecryptionError(
            "stored value did not authenticate — wrong FIELD_ENCRYPTION_KEYS or tampered row"
        ) from exc


def hash_secret(value) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        value = str(value)
    return hmac.new(_hash_key(), value.encode(), hashlib.sha256).hexdigest()


def mask_secret(value, keep: int = 4) -> str:
    if not value:
        return "***"
    text = str(value)
    if len(text) <= keep:
        return "***"
    return f"***{text[-keep:]}"


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
    return value if is_encrypted(value) else encrypt(value)


def _encrypt_json(raw):
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
    _rewrite_table(connection, table, columns, json_columns, _encrypt_text, _encrypt_json, batch_size)


def decrypt_table_columns(connection, table, columns=(), json_columns=(), batch_size=500):
    _rewrite_table(connection, table, columns, json_columns, decrypt, _decrypt_json, batch_size)


def backfill_hash_column(connection, table, source_column, hash_column, batch_size=500):
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
