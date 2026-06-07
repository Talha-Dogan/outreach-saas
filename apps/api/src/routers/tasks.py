from __future__ import annotations
import json
import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl
import redis.asyncio as aioredis
from core.config import settings
from core.redis_client import RedisKeys, get_redis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["tasks"])

class ProxyOverrideRequest(BaseModel):
    server: str = Field(...)
    username: str | None = None
    password: str | None = None

class DispatchTaskRequest(BaseModel):
    action: str = Field(..., pattern=r"^(visit_profile|send_connection|send_message)$")
    target_url: HttpUrl
    message: str | None = Field(None, max_length=300)
    proxy: ProxyOverrideRequest | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class DispatchTaskResponse(BaseModel):
    task_id: str
    status: str
    message: str
    websocket_url: str
    poll_url: str

class LogEntry(BaseModel):
    level: str
    message: str
    timestamp: float

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    message: str | None
    progress_pct: int
    duration_s: float | None
    error: str | None
    logs: list[LogEntry]
    websocket_url: str

_CELERY_STATE_MAP = {"PENDING": "PENDING", "STARTED": "RUNNING", "SUCCESS": "SUCCESS", "FAILURE": "FAILED", "RETRY": "RETRY", "REVOKED": "FAILED"}
_PROGRESS_MAP = {"PENDING": 5, "RUNNING": 50, "RETRY": 30, "SUCCESS": 100, "FAILED": 100, "RATE_LIMITED": 100}

@router.post("/dispatch", response_model=DispatchTaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def dispatch_task(
    body: DispatchTaskRequest,
    user_id: str = "demo_user",
    redis: aioredis.Redis = Depends(get_redis),
) -> DispatchTaskResponse:
    import uuid
    from celery import Celery
    celery_app = Celery(broker=str(settings.REDIS_URL).replace("/0", "") + "/0")
    resolved_proxy: dict | None = None
    if body.proxy is not None:
        resolved_proxy = body.proxy.model_dump(exclude_none=True)
    else:
        stored_raw = await redis.get(RedisKeys.user_settings(user_id))
        if stored_raw:
            stored = json.loads(stored_raw)
            resolved_proxy = stored.get("proxy")
    task_id = str(uuid.uuid4())
    task_payload: dict[str, Any] = {
        "task_id": task_id,
        "user_id": user_id,
        "action": body.action,
        "target_url": str(body.target_url),
        "message": body.message,
        "metadata": body.metadata,
        "proxy": resolved_proxy,
    }
    queue_map = {"visit_profile": "outreach:low", "send_connection": "outreach:default", "send_message": "outreach:high"}
    celery_app.send_task("outreach.execute", args=[task_payload], task_id=task_id, queue=queue_map[body.action])
    initial_snapshot = json.dumps({"task_id": task_id, "status": "PENDING", "message": "Queued", "duration_s": None, "error": None})
    await redis.setex(RedisKeys.task_result(task_id), settings.TASK_RESULT_TTL_SECONDS, initial_snapshot)
    logger.info("Task dispatched | task_id=%s | user_id=%s | action=%s", task_id, user_id, body.action)
    return DispatchTaskResponse(task_id=task_id, status="PENDING", message="Task accepted and queued.", websocket_url=f"/ws/tasks/{task_id}", poll_url=f"/tasks/{task_id}/status")

@router.get("/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    log_lines: int = 20,
    user_id: str = "demo_user",
    redis: aioredis.Redis = Depends(get_redis),
) -> TaskStatusResponse:
    raw_result = await redis.get(RedisKeys.task_result(task_id))
    if raw_result:
        snapshot = json.loads(raw_result)
        domain_status = snapshot.get("status", "PENDING")
    else:
        domain_status = "PENDING"
        snapshot = {"task_id": task_id, "status": "PENDING", "message": "Waiting for worker.", "duration_s": None, "error": None}
    raw_logs: list[str] = await redis.lrange(RedisKeys.task_log(task_id), -log_lines, -1)
    parsed_logs: list[LogEntry] = []
    for raw in raw_logs:
        try:
            entry = json.loads(raw)
            parsed_logs.append(LogEntry(level=entry.get("level", "INFO"), message=entry.get("message", ""), timestamp=entry.get("timestamp", 0.0)))
        except (json.JSONDecodeError, KeyError):
            continue
    return TaskStatusResponse(
        task_id=task_id,
        status=domain_status,
        message=snapshot.get("message"),
        progress_pct=_PROGRESS_MAP.get(domain_status, 0),
        duration_s=snapshot.get("duration_s"),
        error=snapshot.get("error"),
        logs=parsed_logs,
        websocket_url=f"/ws/tasks/{task_id}",
    )
