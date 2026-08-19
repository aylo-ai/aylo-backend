import logging
import time

from celery import shared_task

from apps.shared.addons.redis import redis_client

from .instagram_messaging import process_instagram_message
from .telegram import process_message_task

logger = logging.getLogger(__name__)

WAIT_SECONDS = 2


@shared_task(name="apps.integration.tasks.process_collected_messages")
def process_collected_messages(chat_id, bot_token=None, messaging=None, chat_username=None,
                               username=None, account_id=None):
    user_key = f"messages:{chat_id}"
    last_seen_key = f"last_seen:{chat_id}"

    last_seen = float(redis_client.get(last_seen_key) or 0)
    if time.time() - last_seen < WAIT_SECONDS:
        return

    messages = redis_client.lrange(user_key, 0, -1)
    if not messages:
        return
    combined_message = ", ".join(m for m in messages)

    redis_client.delete(user_key)
    redis_client.delete(last_seen_key)

    if bot_token:
        process_message_task.delay(chat_id, combined_message, bot_token, chat_username, username)
    else:
        resolved_account_id = account_id
        try:
            if resolved_account_id is None and messaging:
                resolved_account_id = messaging[0].get("recipient", {}).get("id")
        except Exception:
            resolved_account_id = None
        resolved_account_id = resolved_account_id or chat_id
        process_instagram_message.delay(
            account_id=resolved_account_id, combined_message=combined_message, user_message=messaging
        )
