from django.core.management.base import BaseCommand

from apps.assistant.models import Assistant
from apps.shared.ai_service import knowledge_base


class Command(BaseCommand):
    help = "Rebuild assistant knowledge bases on OpenAI vector stores."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would happen without calling OpenAI or writing anything.",
        )
        parser.add_argument(
            "--assistant", type=str, default=None,
            help="Migrate a single assistant by id.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        assistants = Assistant.objects.prefetch_related("files")
        if options["assistant"]:
            assistants = assistants.filter(id=options["assistant"])

        migrated = skipped = failed = 0

        for assistant in assistants:
            files = [f for f in assistant.files.all() if f.file]
            label = f"{assistant.name} ({assistant.id})"

            if not files:
                self.stdout.write(f"  skip  {label} — no files")
                skipped += 1
                continue

            if assistant.vector_id and assistant.vector_id.startswith("vs_"):
                self.stdout.write(f"  skip  {label} — already on OpenAI")
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(f"  would migrate {label} — {len(files)} file(s)")
                migrated += 1
                continue

            try:
                store_id, file_ids = self._migrate(assistant, files)
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"  FAIL  {label} — {exc}"))
                failed += 1
                continue

            if not file_ids:
                self.stderr.write(self.style.WARNING(f"  FAIL  {label} — nothing indexed"))
                failed += 1
                continue

            self.stdout.write(
                self.style.SUCCESS(f"  ok    {label} — {len(file_ids)} file(s) → {store_id}")
            )
            migrated += 1

        summary = f"migrated={migrated} skipped={skipped} failed={failed}"
        self.stdout.write(self.style.SUCCESS(f"\n{'[dry run] ' if dry_run else ''}{summary}"))

    def _migrate(self, assistant, files):
        store_id = knowledge_base.create_store(f"kb-{assistant.id}")

        indexed = []
        for upload in files:
            file_id = knowledge_base.add_stored_file(
                store_id, upload.file, upload.filename
            )
            if file_id:
                upload.file_id = file_id
                upload.save(update_fields=["file_id", "updated_time"])
                indexed.append(file_id)
            else:
                self.stdout.write(f"        could not index {upload.filename}")

        if not indexed:
            knowledge_base.delete_store(store_id)
            return store_id, []

        assistant.vector_id = store_id
        assistant.save(update_fields=["vector_id", "updated_time"])
        return store_id, indexed
