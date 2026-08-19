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

_ALLOWED_LOOKUPS = frozenset({"isnull"})


class EncryptedFieldMixin:
    def get_prep_value(self, value):
        return crypto.encrypt(super().get_prep_value(value))

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        try:
            return crypto.decrypt(value)
        except crypto.DecryptionError:
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
    pass


class EncryptedCharField(EncryptedFieldMixin, models.CharField):
    def db_type(self, connection):
        return connection.data_types["TextField"]


class EncryptedJSONField(EncryptedFieldMixin, models.JSONField):
    def get_prep_value(self, value):
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
