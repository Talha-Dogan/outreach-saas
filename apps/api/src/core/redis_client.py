from __future__ import annotations
import logging
from typing import AsyncGenerator
import redis.asyncio as aioredis
from core.config import settings

logger = logging.getLogger(__name__)

_redis_pool: aioredis.Redis | None = None

def get_redis_pool() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            str(settings.REDIS_URL),
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=30,
            max_connections=20,
        )
        logger.info("Redis connection pool initialised")
    return _redis_pool

async def close_redis_pool() -> None:
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None
        logger.info("Redis connection pool closed")

async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    yield get_redis_pool()

class RedisKeys:
    SESSION_TTL = 86_400
    RATE_LIMIT_TTL = 86_400
    REFRESH_TOKEN_TTL = 7 * 86_400
    TASK_RESULT_TTL = 3_600
    TASK_LOG_TTL = 3_600

    @staticmethod
    def session(user_id: str) -> str:
        return f"session:{user_id}"

    @staticmethod
    def rate_limit(user_id: str) -> str:
        return f"rate:{user_id}"

    @staticmethod
    def refresh_token(user_id: str) -> str:
        return f"refresh_token:{user_id}"

    @staticmethod
    def user_settings(user_id: str) -> str:
        return f"user_settings:{user_id}"

    @staticmethod
    def task_result(task_id: str) -> str:
        return f"task_result:{task_id}"

    @staticmethod
    def task_log(task_id: str) -> str:
        return f"task_log:{task_id}"

    @staticmethod
    def task_pubsub(task_id: str) -> str:
        return f"task_updates:{task_id}"
