"""Encrypt the Payme card tokens already stored on `Card`.

See apps/integration/migrations/0045 for the rollout notes — same chunked,
idempotent, resumable shape.
"""
from django.db import migrations

from apps.shared.addons import crypto

TABLE = "Card"
COLUMNS = ["card_token"]


def encrypt_rows(apps, schema_editor):
    crypto.encrypt_table_columns(schema_editor.connection, TABLE, COLUMNS)


def decrypt_rows(apps, schema_editor):
    crypto.decrypt_table_columns(schema_editor.connection, TABLE, COLUMNS)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("payment", "0021_encrypt_secrets_and_pii"),
    ]

    operations = [
        migrations.RunPython(encrypt_rows, decrypt_rows),
    ]
