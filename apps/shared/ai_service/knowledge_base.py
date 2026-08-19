import logging
import os
import time
from io import BytesIO
from typing import Optional

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


def add_stored_file(store_id: str, fieldfile, filename: Optional[str] = None) -> Optional[str]:
    filename = os.path.basename(filename or fieldfile.name or "") or "file"

    if not is_supported(filename):
        logger.info("Skipping unsupported file %s", filename)
        return None

    try:
        with fieldfile.open("rb") as handle:
            content = handle.read()
    except Exception as exc:
        logger.error("Could not read %s from storage: %s", filename, exc)
        return None

    if not content:
        logger.info("File %s is empty; skipping", filename)
        return None

    return _upload(store_id, content, filename)


def add_text(store_id: str, text: str, filename: str = "knowledge_base.txt") -> Optional[str]:
    if not text:
        return None
    return _upload(store_id, text.encode("utf-8"), filename)


def has_knowledge_base(assistant) -> bool:
    if assistant.vector_id:
        return True
    return assistant.files.exists()


def ensure_store(assistant, name_hint: Optional[str] = None) -> str:
    if is_openai_store(assistant.vector_id):
        return assistant.vector_id

    store_id = create_store(name_hint or f"kb-{assistant.id}")
    assistant.vector_id = store_id
    assistant.save(update_fields=["vector_id", "updated_time"])
    return store_id


def _upload(store_id: str, content: bytes, filename: str) -> Optional[str]:
    buffer = BytesIO(content)
    buffer.name = filename

    client = get_client()

    try:
        indexed = client.vector_stores.files.upload(
            vector_store_id=store_id, file=buffer
        )
        indexed = _poll(client, store_id, indexed, filename)
    except Exception as exc:
        logger.error("Failed to index %s into %s: %s", filename, store_id, exc)
        return None

    if indexed is None:
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


def _poll(client, store_id: str, indexed, filename: str):
    deadline = time.monotonic() + INDEX_TIMEOUT_SECONDS

    while getattr(indexed, "status", None) == "in_progress":
        if time.monotonic() >= deadline:
            logger.error(
                "Gave up waiting for %s to index into %s after %ss",
                filename, store_id, INDEX_TIMEOUT_SECONDS,
            )
            return None
        time.sleep(INDEX_POLL_SECONDS)
        indexed = client.vector_stores.files.retrieve(
            indexed.id, vector_store_id=store_id
        )

    return indexed
