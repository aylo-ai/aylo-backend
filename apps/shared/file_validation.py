"""Size and type checks for user uploads.

These run in serializer ``validate()`` methods, *before* the file is written to
object storage or handed to a paid API. That ordering is the point: the previous
audio path called ``file.read()`` and then Whisper with no limit of any kind, so
a single request could buffer 100 MB in a gunicorn worker, hold it for the
600-second proxy timeout, and bill an unbounded amount of transcription.

The extension allowlist is a containment measure rather than a content check —
nothing here proves a ``.pdf`` is a PDF. What it does guarantee is that whatever
is stored cannot be fetched back as an active document type. Real content
sniffing needs libmagic and is noted as an open item.
"""

import os

from django.utils.translation import gettext_lazy as _

from apps.shared.addons.validations import raise_validation_error
from apps.shared.ai_service.knowledge_base import SUPPORTED_EXTENSIONS

MB = 1024 * 1024

# The vector store only indexes these, so anything else is dead weight we would
# be storing and paying for. `.html` is deliberately excluded from the earlier
# set: it is indexable but is also a stored-XSS payload if it is ever served
# from a browsable origin, and its content is reachable as `.txt` or `.md`.
DOCUMENT_EXTENSIONS = frozenset(SUPPORTED_EXTENSIONS - {".html"})

# OpenAI's transcription endpoint rejects anything above 25 MB, so accepting
# more only buys us a slower, more expensive rejection.
AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".oga", ".wav", ".webm", ".flac"}
)

MAX_DOCUMENT_BYTES = 30 * MB
MAX_AUDIO_BYTES = 25 * MB
MAX_IMAGE_BYTES = 10 * MB

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})


def validate_upload(file, allowed_extensions, max_bytes, field="file"):
    """Reject an upload that is too large or of an unaccepted type.

    Returns the file unchanged so it can be used inline in ``validate()``.
    """
    if not file:
        return file

    size = getattr(file, "size", None)
    if size is not None and size > max_bytes:
        raise_validation_error(
            data={field: _("Fayl hajmi %(limit)s MB dan oshmasligi kerak.") % {
                "limit": max_bytes // MB
            }},
            message=_("Fayl juda katta."),
        )

    extension = os.path.splitext(getattr(file, "name", "") or "")[1].lower()
    if extension not in allowed_extensions:
        raise_validation_error(
            data={field: _("“%(ext)s” turidagi fayllar qabul qilinmaydi.") % {
                "ext": extension or "?"
            }},
            message=_("Fayl turi qo‘llab-quvvatlanmaydi."),
        )

    return file


def validate_document(file, field="file"):
    return validate_upload(file, DOCUMENT_EXTENSIONS, MAX_DOCUMENT_BYTES, field)


def validate_audio(file, field="audio_file"):
    return validate_upload(file, AUDIO_EXTENSIONS, MAX_AUDIO_BYTES, field)


def validate_image(file, field="message_image"):
    return validate_upload(file, IMAGE_EXTENSIONS, MAX_IMAGE_BYTES, field)
