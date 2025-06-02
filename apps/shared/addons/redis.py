import json
from datetime import datetime
from typing import Optional

from redis import Redis

from config.settings import REDIS_CREDENTIALS, REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD

redis_connection: Optional[Redis] = None


def get_redis_connection() -> Redis:
    global redis_connection

    if redis_connection is None:
        redis_connection = Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            decode_responses=True
        )

    return redis_connection



def add_to_redis_cache(key: str, value: str, exp_time: Optional[int] = None) -> None:
    """Add key-value pair to Redis cache."""
    print(f"Adding {key} to Redis cache")
    redis = get_redis_connection()
    redis.set(key, value)
    if exp_time:
        redis.expire(key, exp_time)
    print(f"Added {key} to Redis cache.")


def get_from_redis_cache(key: str) -> Optional[str]:
    """Get value from Redis cache."""
    print(f"Getting {key} from Redis cache")
    redis = get_redis_connection()
    value = None
    if key is not None:
        value = redis.get(key)
        if value is not None:
            value = str(value)
    print(f"Got {key} from Redis cache.")
    return value


def publish_message_to_ws(conversation_id, message, sender="assistant", run_status=None):
    redis = get_redis_connection()
    payload = {
        "conversation_id": str(conversation_id),
        "message": message,
        "sender": sender,
        "run_status": run_status,
        "timestamp": datetime.now().isoformat()
    }
    redis.publish("chat-messages", json.dumps(payload))
