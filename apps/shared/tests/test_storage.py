"""Storage layer: key generation, presigned URLs, and the guards around them.

Media moved from AWS S3 to self-hosted MinIO. Most of what is asserted here is
not "does the backend work" — django-storages handles that — but the specific
ways the previous configuration was wrong, so that a future edit reintroducing
one of them fails loudly.
"""

from unittest import mock

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage, storages
from django.test import SimpleTestCase, TestCase

from apps.shared.storages import MAX_KEY_LENGTH, MediaStorage, build_media_key


def make_storage(**overrides):
    options = {
        "bucket_name": "aylo-media",
        "endpoint_url": "http://minio:9000",
        "public_endpoint_url": "https://api.aylo.uz",
        "access_key": "testkey",
        "secret_key": "testsecret",
        "region_name": "us-east-1",
        "addressing_style": "path",
        "signature_version": "s3v4",
        "querystring_expire": 3600,
    }
    options.update(overrides)
    return MediaStorage(**options)


class BuildMediaKeyTests(SimpleTestCase):
    def test_two_uploads_of_the_same_name_get_different_keys(self):
        """The regression that mattered most: colliding keys shared one object.

        `assistant/<id>/files/catalog.pdf` was generated verbatim from the client
        filename, so a second upload of catalog.pdf produced a second DB row
        pointing at the *same* object. Deleting either row deleted the file out
        from under the other.
        """
        first = build_media_key("assistant/42/files", "catalog.pdf")
        second = build_media_key("assistant/42/files", "catalog.pdf")

        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("assistant/42/files/"))
        self.assertTrue(first.endswith("catalog.pdf"))

    def test_a_very_long_filename_still_fits_the_column(self):
        """Both FileFields are varchar(255); the key must never exceed it."""
        key = build_media_key("assistant/42/files", "x" * 500 + ".pdf")

        self.assertLessEqual(len(key), MAX_KEY_LENGTH)
        self.assertTrue(key.endswith(".pdf"))

    def test_traversal_and_separators_are_stripped(self):
        key = build_media_key("assistant/42/files", "../../../etc/passwd")

        self.assertNotIn("..", key)
        self.assertTrue(key.startswith("assistant/42/files/"))

    def test_a_filename_that_sanitises_to_nothing_still_produces_a_key(self):
        key = build_media_key("assistant/42/files", "..")

        self.assertTrue(key.startswith("assistant/42/files/"))
        self.assertTrue(key.endswith("file"))

    def test_a_missing_filename_does_not_raise(self):
        self.assertTrue(build_media_key("a/b", "").startswith("a/b/"))


class MediaStorageURLTests(SimpleTestCase):
    def test_url_is_presigned_against_the_public_origin(self):
        """Signing with the internal host would produce links no browser can use."""
        url = make_storage().url("assistant/42/files/report.pdf")

        self.assertTrue(url.startswith("https://api.aylo.uz/aylo-media/"))
        self.assertIn("X-Amz-Signature=", url)
        self.assertIn("X-Amz-Expires=3600", url)

    def test_url_falls_back_to_the_internal_endpoint_when_no_public_origin(self):
        url = make_storage(public_endpoint_url=None).url("a/b.pdf")

        self.assertTrue(url.startswith("http://minio:9000/aylo-media/"))
        self.assertIn("X-Amz-Signature=", url)

    def test_expiry_is_configurable(self):
        url = make_storage(querystring_expire=60).url("a/b.pdf")

        self.assertIn("X-Amz-Expires=60", url)

    def test_custom_domain_is_refused(self):
        """S3Boto3Storage.url() returns an UNSIGNED url when custom_domain is set.

        Against a private bucket that is a 403 on every media link, and the
        failure is silent at configuration time. Refuse the combination instead.
        """
        with self.assertRaises(ImproperlyConfigured):
            make_storage(custom_domain="cdn.aylo.uz")

    def test_uploads_never_silently_overwrite(self):
        self.assertFalse(make_storage().file_overwrite)


class StorageSettingsTests(SimpleTestCase):
    def test_tests_do_not_use_a_network_backend(self):
        """Regression: the suite used to issue real PutObject calls.

        `AssistantFileUploadSerializer` tests save a FileField, which reached
        S3Boto3Storage.save(). It only looked green because this checkout had no
        credentials — with them, tests wrote into the live bucket.
        """
        self.assertEqual(
            settings.STORAGES["default"]["BACKEND"],
            "django.core.files.storage.InMemoryStorage",
        )
        self.assertEqual(type(storages["default"]).__name__, "InMemoryStorage")

    def test_media_url_is_not_defined_twice(self):
        """It was set at two places in settings.py with different intent."""
        source = (settings.BASE_DIR / "config" / "settings.py").read_text()

        self.assertEqual(source.count("\nMEDIA_URL"), 1)


class FileCleanupTests(TestCase):
    """Deleting a row must delete its object, including on cascade."""

    def setUp(self):
        from apps.assistant.models import Assistant, Conversation
        from apps.payment.models import Subscription
        from apps.shared.addons.enums import (
            ConversationStatuses, SubscriptionStatuses,
        )
        from apps.user.models import User

        subscription = Subscription.objects.create(
            status=SubscriptionStatuses.ACTIVE.value, remained_request_count=10,
        )
        user = User.objects.create(
            username="cleanup", auth_type="email", email="cleanup@example.com",
            subscription=subscription,
        )
        self.assistant = Assistant.objects.create(
            name="Bot", company_name="Repli", fallback_message="…",
            vector_id="vs_test", user=user,
        )
        self.conversation = Conversation.objects.create(
            assistant=self.assistant, platform="website",
            status=ConversationStatuses.OPEN.value,
        )

    def make_message_with_audio(self):
        from apps.assistant.models import Message
        from apps.shared.addons.enums import MessageTypes, SenderTypes

        message = Message.objects.create(
            conversation=self.conversation,
            sender=SenderTypes.USER.value,
            message_content="hi",
            message_type=MessageTypes.AUDIO.value,
        )
        message.audio_file.save("note.mp3", ContentFile(b"audio-bytes"))
        return message, message.audio_file.name

    def test_deleting_a_message_deletes_its_audio(self):
        message, key = self.make_message_with_audio()
        self.assertTrue(default_storage.exists(key))

        with self.captureOnCommitCallbacks(execute=True):
            message.delete()

        self.assertFalse(default_storage.exists(key))

    def test_cascading_a_conversation_delete_deletes_the_audio(self):
        """A Model.delete() override never saw this path — post_delete does."""
        _, key = self.make_message_with_audio()
        self.assertTrue(default_storage.exists(key))

        with self.captureOnCommitCallbacks(execute=True):
            self.conversation.delete()

        self.assertFalse(default_storage.exists(key))

    def test_bulk_delete_deletes_the_audio(self):
        from apps.assistant.models import Message

        _, key = self.make_message_with_audio()

        with self.captureOnCommitCallbacks(execute=True):
            Message.objects.all().delete()

        self.assertFalse(default_storage.exists(key))

    def test_a_rolled_back_delete_leaves_the_file_alone(self):
        """The reason deletion is deferred to commit.

        ATOMIC_REQUESTS wraps every view in a transaction, so post_delete fires
        *before* commit. Deleting eagerly there meant a rollback restored the row
        while its file was already gone from storage — a live row pointing at
        nothing, which is strictly worse than the orphan it replaced.
        """
        from django.db import transaction

        from apps.assistant.models import Message

        message, key = self.make_message_with_audio()
        pk = message.pk  # Model.delete() sets instance.pk to None

        class Rollback(Exception):
            pass

        with self.assertRaises(Rollback):
            with transaction.atomic():
                message.delete()
                raise Rollback

        self.assertTrue(
            Message.objects.filter(pk=pk).exists(), "row should be restored"
        )
        self.assertTrue(default_storage.exists(key), "file must survive the rollback")

    def test_a_storage_failure_does_not_break_the_row_delete(self):
        """Cleanup runs after commit — an object-storage error must not propagate."""
        message, _ = self.make_message_with_audio()

        # default_storage is a lazy proxy; patch the concrete backend class.
        with mock.patch.object(
            type(storages["default"]), "delete", side_effect=OSError("minio down")
        ):
            with self.captureOnCommitCallbacks(execute=True):
                message.delete()  # must not raise

        from apps.assistant.models import Message

        self.assertFalse(Message.objects.filter(pk=message.pk).exists())

    def test_deleting_a_row_without_a_file_is_a_no_op(self):
        from apps.assistant.models import Message
        from apps.shared.addons.enums import SenderTypes

        message = Message.objects.create(
            conversation=self.conversation,
            sender=SenderTypes.USER.value,
            message_content="text only",
        )

        with self.captureOnCommitCallbacks(execute=True):
            message.delete()  # must not raise

        self.assertFalse(Message.objects.filter(pk=message.pk).exists())


class StepImageTests(TestCase):
    """Flow-step images: the field that was missed when keys got longer."""

    def make_step(self):
        from apps.integration.models import Flow, Step

        flow = Flow.objects.create()
        return Step.objects.create(flow=flow)

    def test_an_image_upload_fits_the_column(self):
        """Regression: the new key prefix overflowed varchar(100).

        `integration/flows/<uuid>/steps/<uuid>/image/<uuid>/<name>` came to 146
        characters against a 100-char column, so Storage.get_available_name
        truncated the stem away and raised SuspiciousFileOperation — a 500 on
        every flow-step image upload, for every filename.
        """
        from apps.integration.models import Step

        step = self.make_step()
        step.message_image.save("photo.png", ContentFile(b"not-really-a-png"))

        key = Step.objects.get(pk=step.pk).message_image.name
        self.assertLessEqual(
            len(key), Step._meta.get_field("message_image").max_length
        )
        self.assertTrue(key.startswith("integration/flows/"))
        self.assertTrue(key.endswith("photo.png"))

    def test_a_long_filename_also_fits(self):
        from apps.integration.models import Step

        step = self.make_step()
        step.message_image.save("x" * 300 + ".png", ContentFile(b"bytes"))

        self.assertLessEqual(
            len(step.message_image.name),
            Step._meta.get_field("message_image").max_length,
        )

    def test_deleting_a_step_deletes_its_image(self):
        step = self.make_step()
        step.message_image.save("photo.png", ContentFile(b"bytes"))
        key = step.message_image.name

        with self.captureOnCommitCallbacks(execute=True):
            step.delete()

        self.assertFalse(default_storage.exists(key))
