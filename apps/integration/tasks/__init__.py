"""Celery tasks for the integration app, split by domain.

Every task pins ``name="apps.integration.tasks.<func>"`` so the queue routing in
``config/celery.py`` and the beat schedule in ``config/settings.py`` keep working,
and so in-flight queued messages resolve across deploys. This module re-exports
all public names so ``from apps.integration.tasks import X`` works as before.
"""
from .telegram import (
    process_message_task,
    process_photo_task,
    process_voice_task,
)
from .instagram_messaging import (
    process_instagram_message,
    process_shared_post_message,
)
from .instagram_comments import (
    process_instagram_comment,
    process_instagram_comment_message,
)
from .instagram_flows import (
    handle_postback_event_task,
    send_step_message_task,
)
from .collector import (
    WAIT_SECONDS,
    process_collected_messages,
)
from .broadcast import (
    get_broadcast_recipients,
    send_broadcast_task,
    send_message_integration_task,
)
from .billz import (
    fetch_and_save_billz_products,
    update_billz_products_hourly,
)

__all__ = [
    "WAIT_SECONDS",
    "fetch_and_save_billz_products",
    "get_broadcast_recipients",
    "handle_postback_event_task",
    "process_collected_messages",
    "process_instagram_comment",
    "process_instagram_comment_message",
    "process_instagram_message",
    "process_message_task",
    "process_photo_task",
    "process_shared_post_message",
    "process_voice_task",
    "send_broadcast_task",
    "send_message_integration_task",
    "send_step_message_task",
    "update_billz_products_hourly",
]
