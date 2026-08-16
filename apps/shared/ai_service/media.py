"""Voice notes and photos, on OpenAI.

Both helpers degrade instead of raising: a failed transcription or a failed image
read returns a short message the agent can work with, rather than killing the turn.
"""
import base64
import logging
import mimetypes
from io import BytesIO
from typing import Optional, Tuple

import requests
from apps.shared import http

from .client import TRANSCRIBE_MODEL, VISION_MODEL, get_client

logger = logging.getLogger(__name__)

TRANSCRIBE_FAILED = "[The customer sent a voice message that could not be transcribed.]"
IMAGE_FAILED = "[The customer sent an image that could not be read.]"

VISION_PROMPT = (
    "Describe what the customer is showing you. Identify any product, model, brand, "
    "colour or text visible in the image, and note what they are most likely asking "
    "about. Be concise and factual — this description is passed to a sales assistant."
)


def transcribe_audio(audio_bytes: bytes, filename: str = "voice.mp3") -> Tuple[str, int, int]:
    """Transcribe a voice note. Returns (text, input_tokens, output_tokens).

    Whisper is not billed per token, so the token counts are always zero. They are
    returned anyway to keep the shape callers already expect.
    """
    if not audio_bytes:
        return TRANSCRIBE_FAILED, 0, 0

    buffer = BytesIO(audio_bytes)
    buffer.name = filename

    try:
        result = get_client().audio.transcriptions.create(
            model=TRANSCRIBE_MODEL, file=buffer, response_format="text"
        )
    except Exception as exc:
        logger.error("Transcription failed: %s", exc)
        return TRANSCRIBE_FAILED, 0, 0

    text = (result if isinstance(result, str) else getattr(result, "text", "")).strip()
    return text or TRANSCRIBE_FAILED, 0, 0


def transcribe_url(audio_url: str) -> Tuple[str, int, int]:
    content = _download(audio_url)
    if content is None:
        return TRANSCRIBE_FAILED, 0, 0
    filename = audio_url.split("?")[0].split("/")[-1] or "voice.mp3"
    return transcribe_audio(content, filename)


def analyze_image(image_url: str) -> str:
    """Describe an image so the agent can answer questions about it."""
    content = _download(image_url)
    if content is None:
        return IMAGE_FAILED

    mime = mimetypes.guess_type(image_url.split("?")[0])[0] or "image/jpeg"
    if not mime.startswith("image/"):
        logger.warning("%s is not an image (%s)", image_url, mime)
        return IMAGE_FAILED

    data_url = f"data:{mime};base64,{base64.b64encode(content).decode()}"

    try:
        response = get_client().responses.create(
            model=VISION_MODEL,
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": VISION_PROMPT},
                    {"type": "input_image", "image_url": data_url},
                ],
            }],
        )
    except Exception as exc:
        logger.error("Image analysis failed for %s: %s", image_url, exc)
        return IMAGE_FAILED

    text = (getattr(response, "output_text", "") or "").strip()
    return text or IMAGE_FAILED


def _download(url: str) -> Optional[bytes]:
    try:
        response = http.get(url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        # Log the object path only. A presigned URL's query string is a bearer
        # credential for someone else's file.
        logger.error("Could not download %s: %s", url.split("?")[0], exc)
        return None
    return response.content or None
