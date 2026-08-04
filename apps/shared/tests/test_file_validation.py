"""Upload limits.

The audio path had no limit of any kind: a 100 MB file was buffered whole in a
gunicorn worker, `.read()` doubled it, and the request then blocked on a paid
transcription for as long as the proxy allowed. The document path checked size
but not type, so anything at all could be stored and served back.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from apps.shared.addons.validations import CustomValidationError
from apps.shared.file_validation import (
    MAX_AUDIO_BYTES,
    MAX_DOCUMENT_BYTES,
    validate_audio,
    validate_document,
)


def upload(name, size=10):
    return SimpleUploadedFile(name, b"x" * size)


class AudioValidationTests(SimpleTestCase):
    def test_an_oversized_file_is_refused_before_transcription(self):
        big = upload("voice.mp3", MAX_AUDIO_BYTES + 1)

        with self.assertRaises(CustomValidationError):
            validate_audio(big)

    def test_the_limit_matches_what_the_transcription_api_accepts(self):
        """Accepting more than the API does only buys a slower rejection."""
        self.assertEqual(MAX_AUDIO_BYTES, 25 * 1024 * 1024)

    def test_a_non_audio_extension_is_refused(self):
        with self.assertRaises(CustomValidationError):
            validate_audio(upload("payload.exe"))

    def test_ordinary_voice_notes_pass(self):
        for name in ("voice.mp3", "voice.ogg", "voice.m4a", "voice.webm", "VOICE.WAV"):
            with self.subTest(name=name):
                self.assertIsNotNone(validate_audio(upload(name)))

    def test_no_audio_is_not_an_error(self):
        """Text-only messages carry no audio; validation must not reject them."""
        self.assertIsNone(validate_audio(None))


class DocumentValidationTests(SimpleTestCase):
    def test_an_oversized_document_is_refused(self):
        with self.assertRaises(CustomValidationError):
            validate_document(upload("book.pdf", MAX_DOCUMENT_BYTES + 1))

    def test_an_unsupported_extension_is_refused(self):
        """The old check was size-only — any type at all could be stored."""
        for name in ("malware.exe", "shell.sh.bin", "archive.zip", "noext"):
            with self.subTest(name=name), self.assertRaises(CustomValidationError):
                validate_document(upload(name))

    def test_html_is_refused_even_though_the_vector_store_indexes_it(self):
        """Stored HTML served from the API origin is a stored-XSS payload."""
        with self.assertRaises(CustomValidationError):
            validate_document(upload("payload.html"))

    def test_knowledge_base_documents_pass(self):
        for name in ("price.pdf", "notes.txt", "data.csv", "sheet.xlsx", "doc.docx"):
            with self.subTest(name=name):
                self.assertIsNotNone(validate_document(upload(name)))
