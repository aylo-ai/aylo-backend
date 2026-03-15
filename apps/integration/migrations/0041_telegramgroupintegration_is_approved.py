from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integration', '0040_broadcast'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramgroupintegration',
            name='is_approved',
            field=models.BooleanField(default=False),
        ),
    ]
