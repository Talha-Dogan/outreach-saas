from __future__ import annotations
import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])

_TERMINAL_STATUSES = {"SUCCESS", "FAILED", "RATE_LIMITED"}

@router.websocket("/ws/tasks/{task_id}")
async def task_status_websocket(task_id: str, websocket: WebSocket) -> None:
    await websocket.accept()
    logger.info("WebSocket connected for task_id=%s", task_id)
    redis_client = aioredis.from_url("redis://localhost:6379/0", decode_responses=True)
    pubsub = redis_client.pubsub()
    channel = f"task_updates:{task_id}"
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            data = json.loads(message["data"])
            await websocket.send_json(data)
            if data.get("status") in _TERMINAL_STATUSES:
                break
    except WebSocketDisconnect:
        logger.info("Client disconnected from task_id=%s", task_id)
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await redis_client.aclose()
        await websocket.close()
