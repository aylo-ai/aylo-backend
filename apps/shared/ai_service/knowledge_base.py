"""Knowledge base management on OpenAI vector stores.

The agent reads these through the native `file_search` tool, so all this module
does is get files in and out of a store and keep `Assistant.vector_id` accurate.
"""
import logging
import mimetypes
import time
from io import BytesIO
from typing import Iterable, List, Optional, Tuple

import requests

from .client import get_client
from .tools import is_openai_store

logger = logging.getLogger(__name__)

INDEX_TIMEOUT_SECONDS = 120
INDEX_POLL_SECONDS = 2

SUPPORTED_EXTENSIONS = {
    ".c", ".cpp", ".cs", ".css", ".doc", ".docx", ".go", ".html", ".java",
    ".js", ".json", ".md", ".pdf", ".php", ".pptx", ".py", ".rb", ".sh",
    ".tex", ".ts", ".txt", ".csv", ".xlsx",
}


def is_supported(filename: str) -> bool:
    lowered = (filename or "").lower()
    return any(lowered.endswith(ext) for ext in SUPPORTED_EXTENSIONS)


def create_store(name: str) -> str:
    store = get_client().vector_stores.create(name=name)
    logger.info("Created vector store %s (%s)", store.id, name)
    return store.id


def delete_store(store_id: str) -> bool:
    if not store_id:
        return False
    try:
        get_client().vector_stores.delete(vector_store_id=store_id)
        return True
    except Exception as exc:
        logger.warning("Failed to delete vector store %s: %s", store_id, exc)
        return False


def delete_file(store_id: str, file_id: str) -> bool:
    if not store_id or not file_id:
        return False
    try:
        get_client().vector_stores.files.delete(vector_store_id=store_id, file_id=file_id)
        return True
    except Exception as exc:
        logger.warning("Failed to delete file %s from store %s: %s", file_id, store_id, exc)
        return False


def add_file(store_id: str, file_url: str) -> Optional[str]:
    """Download a file and index it. Returns the file id, or None on failure."""
    content, filename = _download(file_url)
    if content is None:
        return None
    return _upload(store_id, content, filename)


def add_text(store_id: str, text: str, filename: str = "knowledge_base.txt") -> Optional[str]:
    if not text:
        return None
    return _upload(store_id, text.encode("utf-8"), filename)


def ensure_store(assistant, name_hint: Optional[str] = None) -> str:
    """Return the assistant's store id, creating and saving one if needed.

    A legacy Gemini id (`fileSearchStores/...`) is not a usable OpenAI store, so
    it is replaced with a fresh one instead of being uploaded into — OpenAI 404s
    on those names.
    """
    if is_openai_store(assistant.vector_id):
        return assistant.vector_id

    store_id = create_store(name_hint or f"kb-{assistant.id}")
    assistant.vector_id = store_id
    assistant.save(update_fields=["vector_id", "updated_time"])
    return store_id


def replace_files(assistant, file_urls: Iterable[str]) -> Tuple[str, List[str]]:
    """Point the assistant at a brand new store built from `file_urls`.

    A new store is built first and only swapped in once it is ready, so a failed
    rebuild leaves the assistant's current knowledge base intact.
    """
    old_store_id = assistant.vector_id
    new_store_id = create_store(f"kb-{assistant.id}")

    file_ids = []
    for url in file_urls:
        file_id = add_file(new_store_id, url)
        if file_id:
            file_ids.append(file_id)

    if not file_ids:
        logger.warning("No files indexed for assistant %s; keeping the old store", assistant.id)
        delete_store(new_store_id)
        return old_store_id, []

    assistant.vector_id = new_store_id
    assistant.save(update_fields=["vector_id", "updated_time"])

    if old_store_id:
        delete_store(old_store_id)

    return new_store_id, file_ids


# --------------------------------------------------------------------------

def _download(file_url: str) -> Tuple[Optional[bytes], str]:
    filename = file_url.split("?")[0].split("/")[-1] or "file"

    if not is_supported(filename):
        guessed = mimetypes.guess_type(filename)[0]
        logger.info("Skipping unsupported file %s (%s)", filename, guessed)
        return None, filename

    try:
        response = requests.get(file_url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Could not download %s: %s", file_url, exc)
        return None, filename

    if not response.content:
        logger.info("File %s is empty; skipping", file_url)
        return None, filename

    return response.content, filename


def _upload(store_id: str, content: bytes, filename: str) -> Optional[str]:
    buffer = BytesIO(content)
    buffer.name = filename

    try:
        indexed = get_client().vector_stores.files.upload_and_poll(
            vector_store_id=store_id, file=buffer
        )
    except Exception as exc:
        logger.error("Failed to index %s into %s: %s", filename, store_id, exc)
        return None

    if getattr(indexed, "status", None) != "completed":
        logger.error(
            "Indexing %s into %s finished as %s: %s",
            filename, store_id, getattr(indexed, "status", None),
            getattr(indexed, "last_error", None),
        )
        return None

    logger.info("Indexed %s into %s as %s", filename, store_id, indexed.id)
    return indexed.id
