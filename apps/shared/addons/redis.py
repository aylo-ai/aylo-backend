import json
import uuid
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


def publish_order(order_id: uuid.UUID, owner_type: str, company_id: uuid.UUID, language: str) -> None:
    """Publish order ID to redis pub/sub channel."""
    channel_name = "orders:channel"
    print(f"Publishing order ID {order_id} to channel {channel_name}")
    # Publish the order ID only
    publish_message = {
        "order_id": order_id,
        "owner_type": owner_type,
        "company_id": company_id,
        "language": language,
    }
    print(f"Publish message: {publish_message}")
    # Get Redis connection and publish the order ID
    get_redis_connection().publish(channel_name, json.dumps(publish_message))


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