"""Index the conversation lookup performed on every inbound message.

Built CONCURRENTLY: a plain CREATE INDEX takes a lock that blocks writes to
``conversation`` for the whole build, and that table is written on every
customer message. Concurrent builds cannot run inside a transaction, hence
``atomic = False``.
"""
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('assistant', '0049_conversation_instructions_version_and_more'),
    ]

    operations = [
        AddIndexConcurrently(
            model_name='conversation',
            index=models.Index(
                fields=['assistant', 'user_id', 'token'],
                name='conv_assistant_user_token_idx',
            ),
        ),
    ]
