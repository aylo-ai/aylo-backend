"""Rebrand: BlogPost.author default and existing rows, Repli AI → Aylo AI.

The default lived in `0001_initial` as "Repli AI Team". Changing the model
field only affects posts created afterwards, so this also rewrites the rows
already in the table — otherwise the blog would keep serving the old brand as
its byline. The reverse restores the previous value so the migration is not
one-way.
"""

from django.db import migrations, models

OLD = "Repli AI Team"
NEW = "Aylo AI Team"


def rename_author(apps, schema_editor):
    BlogPost = apps.get_model("blog", "BlogPost")
    BlogPost.objects.filter(author=OLD).update(author=NEW)


def restore_author(apps, schema_editor):
    BlogPost = apps.get_model("blog", "BlogPost")
    BlogPost.objects.filter(author=NEW).update(author=OLD)


class Migration(migrations.Migration):

    dependencies = [("blog", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="blogpost",
            name="author",
            field=models.CharField(default=NEW, max_length=100),
        ),
        migrations.RunPython(rename_author, restore_author),
    ]
