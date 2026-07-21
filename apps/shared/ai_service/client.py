"""Single OpenAI client for the whole project.

The client is built lazily so that importing this module never requires a key —
tests and management commands can import the agent without touching the network.
"""
import logging
from typing import Optional

from openai import OpenAI

from config import settings

logger = logging.getLogger(__name__)

# Models. Kept here so there is exactly one place to change them.
CHAT_MODEL = "gpt-4o"
VISION_MODEL = "gpt-4o"
TRANSCRIBE_MODEL = "whisper-1"

_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        _client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=60.0, max_retries=0)
    return _client


def reset_client() -> None:
    """Drop the cached client. Used by tests."""
    global _client
    _client = None
