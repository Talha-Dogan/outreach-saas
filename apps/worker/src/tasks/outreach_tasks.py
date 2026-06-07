from __future__ import annotations
import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator
import redis.asyncio as aioredis
from celery import Task
from celery.utils.log import get_task_logger
from core.automation_worker import CoreAutomationWorker, ProxyConfig, TaskPayload, TaskResult, TaskStatus
from core.redis_client import RedisKeys
from celery_app import celery_app

logger = get_task_logger(__name__)

_MAX_LOG_ENTRIES = 200
_DEFAULT_DAILY_LIMIT = int(os.getenv("DEFAULT_DAILY_LIMIT", "50"))

def _build_redis_client() -> aioredis.Redis:
    return aioredis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        encoding="utf-8",
        decode_responses=True,
    )

async def _append_task_log(redis: aioredis.Redis, task_id: str, level: str, message: str) -> None:
    log_key = RedisKeys.task_log(task_id)
    entry = json.dumps({"level": level, "message": message, "timestamp": time.time()})
    pipe = redis.pipeline()
    pipe.rpush(log_key, entry)
    pipe.ltrim(log_key, -_MAX_LOG_ENTRIES, -1)
    pipe.expire(log_key, RedisKeys.TASK_LOG_TTL)
    await pipe.execute()

async def _persist_task_result(redis: aioredis.Redis, result: TaskResult) -> None:
    snapshot = json.dumps({
        "task_id": result.task_id,
        "status": result.status.name,
        "message": result.message,
        "duration_s": result.duration_s,
        "error": result.error,
    })
    await redis.setex(RedisKeys.task_result(result.task_id), RedisKeys.TASK_RESULT_TTL, snapshot)

@asynccontextmanager
async def _managed_task_execution(task_id: str, redis: aioredis.Redis) -> AsyncGenerator[CoreAutomationWorker, None]:
    worker = CoreAutomationWorker(redis_client=redis)
    try:
        yield worker
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.exception("Unhandled exception in task | task_id=%s | error=%s", task_id, error_msg)
        await _append_task_log(redis, task_id, "ERROR", f"Fatal error: {error_msg}")
        failure_result = TaskResult(task_id=task_id, status=TaskStatus.FAILED, message="Task terminated due to an unhandled exception", error=error_msg)
        await _persist_task_result(redis, failure_result)
        raise
    finally:
        try:
            await worker.force_close()
            logger.debug("force_close() completed for task_id=%s", task_id)
        except Exception as close_exc:
            logger.warning("force_close() raised during cleanup | task_id=%s: %s", task_id, close_exc)
        try:
            await redis.aclose()
        except Exception:
            pass

class OutreachBaseTask(Task):
    abstract = True

@celery_app.task(
    bind=True,
    base=OutreachBaseTask,
    name="outreach.execute",
    queue="outreach:default",
    acks_late=True,
    reject_on_worker_lost=True,
    track_started=True,
    max_retries=0,
)
def execute_outreach_task(self: OutreachBaseTask, raw_payload: dict[str, Any]) -> dict[str, Any]:
    task_id: str = self.request.id
    logger.info("Task received | task_id=%s | action=%s", task_id, raw_payload.get("action"))

    async def _run() -> dict[str, Any]:
        redis = _build_redis_client()
        raw_payload["task_id"] = task_id
        proxy_data: dict | None = raw_payload.pop("proxy", None)
        proxy = ProxyConfig(**proxy_data) if proxy_data else None
        payload = TaskPayload(**raw_payload, proxy=proxy)
        limit_raw = await redis.get(f"settings:daily_limit:{payload.user_id}")
        daily_limit = int(limit_raw) if limit_raw else _DEFAULT_DAILY_LIMIT
        await _append_task_log(redis, task_id, "INFO", "Task picked up by worker")
        async with _managed_task_execution(task_id, redis) as worker:
            result = await worker.execute(payload, daily_limit=daily_limit)
        await _persist_task_result(redis, result)
        await _append_task_log(
            redis, task_id,
            "INFO" if result.status == TaskStatus.SUCCESS else "WARNING",
            f"Task finished: {result.status.name} - {result.message}",
        )
        logger.info("Task finished | task_id=%s | status=%s | duration=%.2fs", task_id, result.status.name, result.duration_s)
        return {"task_id": result.task_id, "status": result.status.name, "message": result.message, "duration_s": result.duration_s, "error": result.error}

    return asyncio.run(_run())
