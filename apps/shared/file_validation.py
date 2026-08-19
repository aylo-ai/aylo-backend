import os

from django.utils.translation import gettext_lazy as _

from apps.shared.addons.validations import raise_validation_error
from apps.shared.ai_service.knowledge_base import SUPPORTED_EXTENSIONS

MB = 1024 * 1024

DOCUMENT_EXTENSIONS = frozenset(SUPPORTED_EXTENSIONS - {".html"})

AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".oga", ".wav", ".webm", ".flac"}
)

MAX_DOCUMENT_BYTES = 30 * MB
MAX_AUDIO_BYTES = 25 * MB
MAX_IMAGE_BYTES = 10 * MB

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})


def validate_upload(file, allowed_extensions, max_bytes, field="file"):
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
