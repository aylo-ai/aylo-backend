import logging
from collections import defaultdict

from django.db import transaction
from django.db.models.signals import post_delete

logger = logging.getLogger(__name__)

_BATCH_SIZE = 1000


def _delete_keys(storage, keys):
    bucket = getattr(storage, "bucket", None)

    if bucket is None:
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
    def handler(sender, instance, **kwargs):
        keys_by_storage = defaultdict(list)
        for field_name in field_names:
            file = getattr(instance, field_name, None)
            if file and file.name:
                keys_by_storage[file.storage].append(file.name)

        if not keys_by_storage:
            return

        def flush(pending=dict(keys_by_storage)):
            for storage, keys in pending.items():
                _delete_keys(storage, keys)

        transaction.on_commit(flush)

    post_delete.connect(
        handler,
        sender=model,
        weak=False,
        dispatch_uid=f"file_cleanup:{model._meta.label}:{','.join(field_names)}",
    )
