from unittest import mock

from django.core.files.base import ContentFile
from django.test import SimpleTestCase

from apps.shared.ai_service import knowledge_base


def fake_store_file(status="completed", file_id="vsf_1"):
    return mock.Mock(id=file_id, status=status, last_error=None)


class AddStoredFileTests(SimpleTestCase):
    def setUp(self):
        self.client = mock.Mock()
        self.client.vector_stores.files.upload.return_value = fake_store_file()
        mock.patch(
            "apps.shared.ai_service.knowledge_base.get_client",
            return_value=self.client,
        ).start()
        self.addCleanup(mock.patch.stopall)

    def field_file(self, content=b"iPhone 15 Pro - 12,500,000 UZS", name="catalogue.txt"):
        handle = ContentFile(content, name=name)
        fieldfile = mock.MagicMock()
        fieldfile.name = f"assistant/1/files/abc/{name}"
        fieldfile.open.return_value.__enter__.return_value = handle
        return fieldfile

    def test_the_bytes_come_from_storage_not_over_http(self):
        with mock.patch("apps.shared.http.get") as get:
            file_id = knowledge_base.add_stored_file("vs_1", self.field_file())

        self.assertEqual(file_id, "vsf_1")
        get.assert_not_called()
        self.client.vector_stores.files.upload.assert_called_once()

    def test_the_uploaded_buffer_carries_the_original_filename(self):
        knowledge_base.add_stored_file("vs_1", self.field_file(), "Katalog 2026.pdf")

        buffer = self.client.vector_stores.files.upload.call_args.kwargs["file"]
        self.assertEqual(buffer.name, "Katalog 2026.pdf")

    def test_an_unsupported_extension_is_never_uploaded(self):
        fieldfile = self.field_file(name="payload.exe")

        self.assertIsNone(knowledge_base.add_stored_file("vs_1", fieldfile, "payload.exe"))
        self.client.vector_stores.files.upload.assert_not_called()
        fieldfile.open.assert_not_called()

    def test_an_empty_object_is_skipped(self):
        self.assertIsNone(knowledge_base.add_stored_file("vs_1", self.field_file(b"")))
        self.client.vector_stores.files.upload.assert_not_called()

    def test_a_storage_failure_degrades_instead_of_raising(self):
        fieldfile = self.field_file()
        fieldfile.open.side_effect = OSError("minio unreachable")

        self.assertIsNone(knowledge_base.add_stored_file("vs_1", fieldfile))

    def test_an_openai_failure_degrades_instead_of_raising(self):
        self.client.vector_stores.files.upload.side_effect = RuntimeError("openai down")

        self.assertIsNone(knowledge_base.add_stored_file("vs_1", self.field_file()))

    def test_a_file_that_finishes_as_failed_returns_no_id(self):
        self.client.vector_stores.files.upload.return_value = fake_store_file("failed")

        self.assertIsNone(knowledge_base.add_stored_file("vs_1", self.field_file()))


class HasKnowledgeBaseTests(SimpleTestCase):
    def test_an_existing_store_counts(self):
        assistant = mock.Mock(vector_id="vs_1")

        self.assertTrue(knowledge_base.has_knowledge_base(assistant))
        assistant.files.exists.assert_not_called()

    def test_an_upload_whose_indexing_has_not_run_yet_counts(self):
        assistant = mock.Mock(vector_id=None)
        assistant.files.exists.return_value = True

        self.assertTrue(knowledge_base.has_knowledge_base(assistant))

    def test_an_assistant_with_no_documents_at_all_does_not(self):
        assistant = mock.Mock(vector_id=None)
        assistant.files.exists.return_value = False

        self.assertFalse(knowledge_base.has_knowledge_base(assistant))


class PollDeadlineTests(SimpleTestCase):
    def setUp(self):
        self.client = mock.Mock()
        self.slept = []
        mock.patch(
            "apps.shared.ai_service.knowledge_base.time.sleep",
            side_effect=self.slept.append,
        ).start()
        self.addCleanup(mock.patch.stopall)

    def test_it_returns_as_soon_as_indexing_completes(self):
        self.client.vector_stores.files.retrieve.side_effect = [
            fake_store_file("in_progress"),
            fake_store_file("completed"),
        ]

        result = knowledge_base._poll(
            self.client, "vs_1", fake_store_file("in_progress"), "catalogue.txt"
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(self.client.vector_stores.files.retrieve.call_count, 2)

    def test_it_does_not_poll_a_file_that_is_already_done(self):
        result = knowledge_base._poll(
            self.client, "vs_1", fake_store_file("completed"), "catalogue.txt"
        )

        self.assertEqual(result.status, "completed")
        self.client.vector_stores.files.retrieve.assert_not_called()
        self.assertEqual(self.slept, [])

    def test_it_gives_up_at_the_timeout_instead_of_looping_forever(self):
        self.client.vector_stores.files.retrieve.return_value = fake_store_file(
            "in_progress"
        )
        clock = iter([0, 1, 2, knowledge_base.INDEX_TIMEOUT_SECONDS + 1])
        with mock.patch(
            "apps.shared.ai_service.knowledge_base.time.monotonic",
            side_effect=lambda: next(clock),
        ):
            result = knowledge_base._poll(
                self.client, "vs_1", fake_store_file("in_progress"), "catalogue.txt"
            )

        self.assertIsNone(result)

    def test_the_declared_poll_interval_is_the_one_used(self):
        self.client.vector_stores.files.retrieve.side_effect = [
            fake_store_file("completed")
        ]

        knowledge_base._poll(
            self.client, "vs_1", fake_store_file("in_progress"), "catalogue.txt"
        )

        self.assertEqual(self.slept, [knowledge_base.INDEX_POLL_SECONDS])
