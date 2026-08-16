"""Model fields that encrypt their value at rest.

The fields are transparent: assign and read plaintext, the database only ever
sees ``"v1:<fernet-token>"``. See ``apps/shared/addons/crypto.py`` for the
cipher, the version prefix and the key-rotation story.

Not indexable, not filterable
-----------------------------
Fernet is randomised, so the same plaintext produces a different ciphertext on
every write. ``WHERE col = 'x'``, ``LIKE``, ``ORDER BY`` and any index on the
column are therefore meaningless, and the fields **refuse** every lookup except
``isnull`` rather than silently returning an empty queryset.

When a column really has to be searched by exact value, add a companion
``<name>_hash`` column (``models.CharField(max_length=crypto.HASH_HEX_LENGTH)``)
holding ``crypto.hash_secret(value)``, declare it in the model's
``ENCRYPTED_HASH_LOOKUPS`` and give the model an
``EncryptedLookupQuerySet``-based manager. ``filter(col=plaintext)`` is then
rewritten to ``filter(col_hash=<digest>)`` automatically — existing call sites
keep working and stay indexed. ``Integration.api_token`` is the only column
that needs this today (every inbound Telegram webhook resolves the integration
by bot token).

Substring search (``icontains``) cannot be preserved at all; callers that used
it on a now-encrypted column had to drop it.
"""
from __future__ import annotations

import json
import logging

from django.core.exceptions import FieldError
from django.db import models
from django.db.models import Q

from apps.shared.addons import crypto

logger = logging.getLogger(__name__)

__all__ = [
    "EncryptedCharField",
    "EncryptedJSONField",
    "EncryptedLookupQuerySet",
    "EncryptedTextField",
]

#: The only lookup that still means something on a randomised ciphertext.
_ALLOWED_LOOKUPS = frozenset({"isnull"})


class EncryptedFieldMixin:
    """Encrypt on write, decrypt on read, pass legacy plaintext through."""

    def get_prep_value(self, value):
        return crypto.encrypt(super().get_prep_value(value))

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        try:
            return crypto.decrypt(value)
        except crypto.DecryptionError:
            # Fail closed: handing back the raw blob would push a corrupt secret
            # into an outbound API call or render ciphertext to a customer.
            logger.error(
                "Could not decrypt %s.%s — check FIELD_ENCRYPTION_KEYS",
                self.model._meta.label if hasattr(self, "model") else "?",
                self.name,
            )
            raise

    def get_lookup(self, lookup_name):
        if lookup_name not in _ALLOWED_LOOKUPS:
            raise FieldError(
                f"{self.model._meta.label}.{self.name} is encrypted at rest and cannot "
                f"be queried with '{lookup_name}'. Use the companion *_hash column for "
                f"exact lookups (see apps/shared/fields.py)."
            )
        return super().get_lookup(lookup_name)


class EncryptedTextField(EncryptedFieldMixin, models.TextField):
    """``TextField`` stored encrypted. Not indexable — see the module docstring."""


class EncryptedCharField(EncryptedFieldMixin, models.CharField):
    """``CharField`` stored encrypted. Not indexable — see the module docstring.

    ``max_length`` keeps validating the *plaintext*, but the column is created
    as ``text``: a Fernet token is roughly ``4/3 * len + 100`` characters, so a
    ``varchar(255)`` would overflow on any realistic value. On Postgres ``text``
    and ``varchar`` are the same storage, so nothing is lost.
    """

    def db_type(self, connection):
        return connection.data_types["TextField"]


class EncryptedJSONField(EncryptedFieldMixin, models.JSONField):
    """``JSONField`` whose whole document is encrypted.

    The column stays ``jsonb`` and holds a single JSON *string* — the ciphertext
    — so no schema conversion is needed and legacy rows (real JSON objects) are
    still readable. Key lookups (``metadata__foo``) are impossible by
    construction and raise; read the document and index into it in Python.
    """

    def get_prep_value(self, value):
        # `JSONField` serialises whatever this returns, so returning the
        # ciphertext string lands a JSON *string* in the jsonb column.
        if value is None:
            return None
        return crypto.encrypt(json.dumps(value, cls=self.encoder))

    def from_db_value(self, value, expression, connection):
        value = models.JSONField.from_db_value(self, value, expression, connection)
        if crypto.is_encrypted(value):
            try:
                return json.loads(crypto.decrypt(value))
            except crypto.DecryptionError:
                logger.error(
                    "Could not decrypt %s.%s — check FIELD_ENCRYPTION_KEYS",
                    self.model._meta.label if hasattr(self, "model") else "?",
                    self.name,
                )
                raise
        return value

    def get_transform(self, name):
        raise FieldError(
            f"{self.model._meta.label}.{self.name} is encrypted at rest; the key "
            f"transform '{name}' cannot be evaluated in SQL. Load the row and index "
            f"into the decrypted document in Python."
        )


class EncryptedLookupQuerySet(models.QuerySet):
    """Rewrites exact lookups on encrypted columns onto their ``*_hash`` column.

    Declare the mapping on the model::

        class Integration(BaseModel):
            ENCRYPTED_HASH_LOOKUPS = {"api_token": "api_token_hash"}
            objects = EncryptedLookupQuerySet.as_manager()

    ``Integration.objects.filter(api_token=token)`` then becomes
    ``filter(api_token_hash=hash_secret(token))``. Doing it here rather than at
    each call site keeps the ~dozen existing lookups (webhook dispatch,
    integration creation, group registration) working and indexed, and means a
    future encrypted-and-searchable column is one dict entry.

    Only exact matches are rewritten; ``__icontains`` and friends still raise,
    because a hash cannot answer them.
    """

    def _hash_lookups(self) -> dict[str, str]:
        return getattr(self.model, "ENCRYPTED_HASH_LOOKUPS", {}) or {}

    def _rewrite_kwargs(self, kwargs):
        mapping = self._hash_lookups()
        if not mapping:
            return kwargs
        rewritten = {}
        for key, value in kwargs.items():
            field, _, lookup = key.partition("__")
            if field in mapping and lookup in ("", "exact"):
                rewritten[mapping[field]] = crypto.hash_secret(value)
            else:
                rewritten[key] = value
        return rewritten

    def _rewrite_q(self, node):
        mapping = self._hash_lookups()
        if not mapping or not isinstance(node, Q):
            return node
        clone = node.__class__()
        clone.connector = node.connector
        clone.negated = node.negated
        for child in node.children:
            if isinstance(child, Q):
                clone.children.append(self._rewrite_q(child))
            elif isinstance(child, tuple):
                key, value = child
                field, _, lookup = key.partition("__")
                if field in mapping and lookup in ("", "exact"):
                    clone.children.append((mapping[field], crypto.hash_secret(value)))
                else:
                    clone.children.append(child)
            else:
                clone.children.append(child)
        return clone

    def _rewrite_args(self, args):
        return tuple(self._rewrite_q(arg) for arg in args)

    def filter(self, *args, **kwargs):
        return super().filter(*self._rewrite_args(args), **self._rewrite_kwargs(kwargs))

    def exclude(self, *args, **kwargs):
        return super().exclude(*self._rewrite_args(args), **self._rewrite_kwargs(kwargs))

    def get(self, *args, **kwargs):
        return super().get(*self._rewrite_args(args), **self._rewrite_kwargs(kwargs))
