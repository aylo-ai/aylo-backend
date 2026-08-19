"""Knowledge base management on OpenAI vector stores.

The agent reads these through the native `file_search` tool, so all this module
does is get files in and out of a store and keep `Assistant.vector_id` accurate.

**Files are read from storage, never downloaded over HTTP.** The previous
`add_file(store_id, file_url)` presigned the object, then fetched the whole thing
back through nginx into `response.content` before copying it into a `BytesIO` for
the SDK — three resident copies of the file plus a full network round trip, for
bytes the process could already reach through the storage backend. On the
2 GB deploy host (`web-green` is capped at `mem_limit: 640m`) that round trip was
the difference between an upload working and a worker being killed. Callers now
hand over the `FieldFile` and this module reads it once.

Indexing is bounded. `upload_and_poll()` polls until OpenAI leaves
`in_progress` with no overall deadline, so one stuck file parked a worker
indefinitely; `_upload` polls itself against `INDEX_TIMEOUT_SECONDS`. Both
constants existed here for exactly this purpose and had no reader.
"""
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
    """Index an object that already lives in storage.

    Takes the model's ``FileField`` value rather than a URL, so the bytes come
    off the storage backend directly instead of being fetched back through the
    public origin. Returns the vector-store file id, or None on failure.
    """
    filename = os.path.basename(filename or fieldfile.name or "") or "file"

    if not is_supported(filename):
        logger.info("Skipping unsupported file %s", filename)
        return None

    try:
        with fieldfile.open("rb") as handle:
            content = handle.read()
    except Exception as exc:
        # Never log the object key's presigned form; the name is enough to act on.
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
    """True once the assistant has a document, indexed or still queued.

    The gates that guard conversations and integrations used to test
    `vector_id` directly, which was safe only while the upload request created
    the store inline. `index_assistant_file` now creates it a moment after the
    upload responds, so `vector_id` is briefly still null on a brand-new
    assistant — and testing it alone told a user who had *just* uploaded a file
    to go and upload a file.
    """
    if assistant.vector_id:
        return True
    return assistant.files.exists()


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


# --------------------------------------------------------------------------

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
    """Wait for OpenAI to finish chunking a file, but not forever.

    The SDK's `upload_and_poll` loops while the status is `in_progress` with no
    overall deadline. Returns None once `INDEX_TIMEOUT_SECONDS` is up, so the
    caller can mark the row and let Celery retry instead of holding a worker.
    """
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
