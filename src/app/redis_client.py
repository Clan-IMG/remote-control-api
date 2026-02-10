import redis.asyncio as redis
from src.app.config import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD,
    db=REDIS_DB,
    decode_responses=True
)


async def get_redis():
    return redis_client


# Queue Names
QUEUE_PENDING = "pixelkid:queue:pending"
QUEUE_PROCESSING = "pixelkid:queue:processing"
QUEUE_COMPLETED = "pixelkid:queue:completed"
QUEUE_FAILED = "pixelkid:queue:failed"

# Keys
KEY_REQUEST_PREFIX = "pixelkid:request:"
KEY_CONTAINER_STATUS = "pixelkid:containers:status"
KEY_CONTAINER_LOAD = "pixelkid:containers:load"
# Sorted set to track processing start times (score = epoch seconds)
KEY_PROCESSING_TIMES = "pixelkid:processing:times"
