"""Encrypt existing conversation PII and message bodies.

`messages` is the largest table in the system — one row per conversation turn —
so nothing here may load it into memory. `crypto.encrypt_table_columns` walks
the table with keyset pagination on the UUID primary key and rewrites 500 rows
per statement.

`atomic = False`: batches commit as they go, so a long run can be interrupted
and resumed. Mixed plaintext/ciphertext is a legal state (the `v1:` prefix
distinguishes them) and re-running is idempotent.
"""
from django.db import migrations

from apps.shared.addons import crypto

CONVERSATION_TABLE = "conversation"
CONVERSATION_COLUMNS = ["client_full_name", "client_phone_email"]
MESSAGE_TABLE = "messages"
MESSAGE_COLUMNS = ["message_content"]


def encrypt_rows(apps, schema_editor):
    connection = schema_editor.connection
    crypto.encrypt_table_columns(connection, CONVERSATION_TABLE, CONVERSATION_COLUMNS)
    crypto.encrypt_table_columns(connection, MESSAGE_TABLE, MESSAGE_COLUMNS)


def decrypt_rows(apps, schema_editor):
    connection = schema_editor.connection
    crypto.decrypt_table_columns(connection, CONVERSATION_TABLE, CONVERSATION_COLUMNS)
    crypto.decrypt_table_columns(connection, MESSAGE_TABLE, MESSAGE_COLUMNS)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("assistant", "0051_encrypt_secrets_and_pii"),
    ]

    operations = [
        migrations.RunPython(encrypt_rows, decrypt_rows),
    ]
