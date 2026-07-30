"""Index both Instagram id columns that ``Integration.instagram_by_id`` ORs over.

Built CONCURRENTLY so the webhook path keeps accepting writes during the
deploy; see the note in assistant/migrations/0050.
"""
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('integration', '0042_alter_commentresponsebutton_type_and_more'),
    ]

    operations = [
        AddIndexConcurrently(
            model_name='integration',
            index=models.Index(fields=['instagram_user_id'], name='integration_ig_user_idx'),
        ),
        AddIndexConcurrently(
            model_name='integration',
            index=models.Index(fields=['instagram_account_id'], name='integration_ig_acct_idx'),
        ),
    ]
