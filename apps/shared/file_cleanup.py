"""Delete stored objects when the rows that reference them are deleted.

Before this module, storage grew monotonically. Models carried a ``delete()``
override that removed the object, but Django only calls ``Model.delete()`` on a
single instance — ``queryset.delete()`` and foreign-key cascades both go
straight to SQL. Deleting one assistant therefore cascaded away every
``AssistantFileUpload`` and ``Message`` row while leaving every knowledge-base
document and voice note in the bucket, unreferenced and unfindable.

``post_delete`` is the fix precisely because Django's deletion collector *does*
emit it for cascaded and bulk deletes, so a single registration covers every
path that can remove a row.

**Deletion is deferred to commit, and that is load-bearing.** ``ATOMIC_REQUESTS``
is on, so every view runs inside a transaction and ``post_delete`` fires *before*
commit. Deleting the object there would mean a later rollback restores the row
while its file is already gone — a live row pointing at nothing, which is worse
than the orphan it replaced. ``transaction.on_commit`` callbacks are discarded on
rollback, so storage is only touched once the delete is durable. Nothing here
tries to batch across a transaction: a buffer keyed to the connection survives a
rollback and would delete files belonging to rows that still exist.

Deletion is best-effort. It runs after commit, so nothing it does can undo the
delete; failures are logged and swallowed, leaving at worst the orphan we had
before.

Known cost, not yet addressed: registering ``post_delete`` makes Django's
deletion collector give up its fast-delete path, so cascades now load rows into
memory and issue one delete per file. For a conversation with thousands of voice
notes that is thousands of round trips. Deleting many objects at once wants a
periodic orphan sweep instead — which would also reach the orphans created before
this module existed, that no signal can see.
"""

import logging
from collections import defaultdict

from django.db import transaction
from django.db.models.signals import post_delete

logger = logging.getLogger(__name__)

# S3 DeleteObjects accepts at most 1000 keys per call.
_BATCH_SIZE = 1000


def _delete_keys(storage, keys):
    """Remove ``keys`` from ``storage``, in bulk when the backend supports it."""
    bucket = getattr(storage, "bucket", None)

    if bucket is None:
        # Local or in-memory storage: no bulk API, and no round trip to save.
        for key in keys:
            try:
                storage.delete(key)
            except Exception:
                logger.warning("Could not delete stored object %s", key, exc_info=True)
        return

    for start in range(0, len(keys), _BATCH_SIZE):
        chunk = keys[start:start + _BATCH_SIZE]
        try:
            response = bucket.delete_objects(
                Delete={"Objects": [{"Key": key} for key in chunk], "Quiet": True}
            )
            for error in response.get("Errors", []):
                logger.warning(
                    "Could not delete stored object %s: %s",
                    error.get("Key"),
                    error.get("Message"),
                )
        except Exception:
            logger.warning(
                "Bulk delete of %d stored object(s) failed", len(chunk), exc_info=True
            )


def register_file_cleanup(model, *field_names):
    """Delete ``field_names`` from storage once a ``model`` row's delete commits."""

    def handler(sender, instance, **kwargs):
        keys_by_storage = defaultdict(list)
        for field_name in field_names:
            file = getattr(instance, field_name, None)
            if file and file.name:
                keys_by_storage[file.storage].append(file.name)

        if not keys_by_storage:
            return

        # Bound to this instance's keys only — see the module docstring on why
        # there is no cross-transaction buffer.
        def flush(pending=dict(keys_by_storage)):
            for storage, keys in pending.items():
                _delete_keys(storage, keys)

        transaction.on_commit(flush)

    # dispatch_uid keeps a double registration (autoreload, ready() running
    # twice) from queueing the same key twice.
    post_delete.connect(
        handler,
        sender=model,
        weak=False,
        dispatch_uid=f"file_cleanup:{model._meta.label}:{','.join(field_names)}",
    )
