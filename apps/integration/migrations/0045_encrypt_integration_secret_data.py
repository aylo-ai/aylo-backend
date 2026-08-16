"""Encrypt the credentials already stored on `integration`.

Runs after 0044 swapped the columns to the encrypted field classes. Rows written
before this point are plaintext; the `v1:` version prefix lets the application
read both, so the deploy and this migration do not have to be simultaneous.

`atomic = False`: the rewrite is chunked and idempotent, so it is better to
commit batch by batch than to hold one long transaction over the table. A
partial run leaves a legal mixed state and can simply be re-run.
"""
from django.db import migrations

from apps.shared.addons import crypto

TABLE = "integration"
TEXT_COLUMNS = ["api_token", "refresh_token"]
JSON_COLUMNS = ["metadata"]


def encrypt_rows(apps, schema_editor):
    connection = schema_editor.connection
    crypto.encrypt_table_columns(connection, TABLE, TEXT_COLUMNS, JSON_COLUMNS)
    crypto.backfill_hash_column(connection, TABLE, "api_token", "api_token_hash")


def decrypt_rows(apps, schema_editor):
    crypto.decrypt_table_columns(
        schema_editor.connection, TABLE, TEXT_COLUMNS, JSON_COLUMNS
    )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("integration", "0044_encrypt_secrets_and_pii"),
    ]

    operations = [
        migrations.RunPython(encrypt_rows, decrypt_rows),
    ]
