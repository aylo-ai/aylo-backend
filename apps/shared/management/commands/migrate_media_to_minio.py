"""Copy media objects out of the legacy AWS S3 bucket into MinIO.

Cutover is key-preserving. Every ``FileField`` in this project stores a
storage-relative key (``assistant/<uuid>/files/<name>``) rather than an absolute
URL — there is no ``AWS_LOCATION`` prefix in play — so once the objects exist in
MinIO under the same keys, pointing the backend at MinIO is the whole migration.
No table is rewritten by this command, and it never writes to the DB at all.

Usage::

    # See what would move, touching nothing:
    python manage.py migrate_media_to_minio --dry-run

    # Copy, skipping keys already present in MinIO (safe to re-run):
    python manage.py migrate_media_to_minio

    # Verify sizes afterwards without copying:
    python manage.py migrate_media_to_minio --verify-only

Objects are streamed one at a time, so a large bucket does not need a large
worker. The command is resumable: interrupt it and re-run, and it picks up the
keys that are not in the destination yet.

Known gap, stated rather than silently accepted: this walks the keys the
database references. The retired ``upload_to_s3()`` helper wrote files to the
bucket *root* with no DB row pointing at them, so those objects are invisible
here. Use ``--include-orphans`` to sweep every remaining key in the source
bucket as well.
"""

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError

# Every (model, field) pair whose objects live in the media bucket.
MEDIA_FIELDS = [
    ("assistant", "Message", "audio_file"),
    ("assistant", "AssistantFileUpload", "file"),
    ("integration", "Step", "message_image"),
]


class Command(BaseCommand):
    help = "Copy media objects from the legacy AWS S3 bucket into MinIO."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what would be copied without transferring anything.",
        )
        parser.add_argument(
            "--verify-only",
            action="store_true",
            help="Compare source and destination sizes; copy nothing.",
        )
        parser.add_argument(
            "--include-orphans",
            action="store_true",
            help="Also copy source keys that no database row references.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=200,
            help="Rows fetched per query (default: 200).",
        )

    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]
        self.verify_only = options["verify_only"]

        source = self._source_client()
        source_bucket = settings.AWS_STORAGE_BUCKET_NAME
        destination = storages["default"]

        if not source_bucket:
            raise CommandError(
                "AWS_STORAGE_BUCKET_NAME is not set — nothing to migrate from."
            )

        keys = self._collect_keys(options["batch_size"])
        self.stdout.write(f"{len(keys)} key(s) referenced by the database.")

        if options["include_orphans"]:
            orphans = self._collect_orphans(source, source_bucket, keys)
            self.stdout.write(f"{len(orphans)} additional key(s) in the bucket.")
            keys.extend(orphans)

        copied = skipped = missing = failed = mismatched = 0

        for key in keys:
            try:
                source_size = self._source_size(source, source_bucket, key)
            except FileNotFoundError:
                missing += 1
                self.stderr.write(f"MISSING in source: {key}")
                continue

            if destination.exists(key):
                if self.verify_only or not self.dry_run:
                    destination_size = destination.size(key)
                    if destination_size != source_size:
                        mismatched += 1
                        self.stderr.write(
                            f"SIZE MISMATCH {key}: "
                            f"source={source_size} destination={destination_size}"
                        )
                        continue
                skipped += 1
                continue

            if self.verify_only:
                missing += 1
                self.stderr.write(f"NOT YET COPIED: {key}")
                continue

            if self.dry_run:
                self.stdout.write(f"would copy {key} ({source_size} bytes)")
                copied += 1
                continue

            try:
                body = source.get_object(Bucket=source_bucket, Key=key)["Body"]
                # save() renames on collision (`key_a1b2c3d.txt`), which would
                # break the whole premise of a key-preserving migration — the DB
                # would point at a key that does not exist. The exists() check
                # above should make that impossible, so treat it as a hard error
                # rather than reporting a copy that went somewhere else.
                written = destination.save(key, body)
                if written != key:
                    destination.delete(written)
                    raise CommandError(
                        f"destination renamed {key} to {written}; refusing to "
                        f"leave the database pointing at a missing object"
                    )
                copied += 1
                self.stdout.write(f"copied {key} ({source_size} bytes)")
            except (ClientError, OSError) as exc:
                failed += 1
                self.stderr.write(f"FAILED {key}: {exc}")

        self.stdout.write("")
        summary = (
            f"copied={copied} skipped={skipped} missing={missing} "
            f"failed={failed} mismatched={mismatched}"
        )
        if failed or mismatched:
            self.stderr.write(self.style.ERROR(summary))
            raise CommandError("Migration finished with errors — re-run to retry.")
        self.stdout.write(self.style.SUCCESS(summary))

    # -- helpers ---------------------------------------------------------

    def _source_client(self):
        if not (settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY):
            raise CommandError(
                "Legacy AWS credentials are not configured; nothing to read from."
            )
        return boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME,
        )

    def _collect_keys(self, batch_size):
        from django.apps import apps as django_apps

        keys = []
        for app_label, model_name, field in MEDIA_FIELDS:
            model = django_apps.get_model(app_label, model_name)
            queryset = (
                model.objects.exclude(**{field: ""})
                .exclude(**{f"{field}__isnull": True})
                .values_list(field, flat=True)
                .iterator(chunk_size=batch_size)
            )
            found = [key for key in queryset if key]
            self.stdout.write(f"  {model_name}.{field}: {len(found)}")
            keys.extend(found)
        # Duplicate keys used to be possible before unique key generation landed;
        # de-duplicate so a shared object is not copied twice.
        return sorted(set(keys))

    def _collect_orphans(self, client, bucket, known_keys):
        known = set(known_keys)
        orphans = []
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for item in page.get("Contents", []):
                if item["Key"] not in known and not item["Key"].endswith("/"):
                    orphans.append(item["Key"])
        return orphans

    def _source_size(self, client, bucket, key):
        try:
            return client.head_object(Bucket=bucket, Key=key)["ContentLength"]
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                raise FileNotFoundError(key) from exc
            raise
