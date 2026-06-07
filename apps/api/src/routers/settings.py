from __future__ import annotations
import json
import logging
import re
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
import redis.asyncio as aioredis
from core.config import settings
from core.redis_client import RedisKeys, get_redis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])

_PROXY_URL_PATTERN = re.compile(r"^(https?|socks[45])://[^\s/$.?#].[^\s]*$", re.IGNORECASE)

class ProxyConfigRequest(BaseModel):
    server: str = Field(..., min_length=10, max_length=256)
    username: str | None = Field(None, min_length=1, max_length=128)
    password: str | None = Field(None, min_length=1, max_length=256)

    @field_validator("server")
    @classmethod
    def _validate_proxy_url(cls, value: str) -> str:
        if not _PROXY_URL_PATTERN.match(value):
            raise ValueError("Proxy server must start with http://, https://, socks5://, or socks4://")
        return value

    @model_validator(mode="after")
    def _credentials_pair_required(self) -> "ProxyConfigRequest":
        has_user = self.username is not None
        has_pass = self.password is not None
        if has_user != has_pass:
            raise ValueError("Proxy username and password must both be provided or both omitted")
        return self

class UpdateSettingsRequest(BaseModel):
    proxy: ProxyConfigRequest | None = None
    daily_limit: int | None = Field(None, ge=1, le=200)

class UserSettingsResponse(BaseModel):
    proxy_server: str | None
    proxy_username: str | None
    proxy_has_password: bool
    daily_limit: int

def _load_settings_from_dict(raw: dict) -> UserSettingsResponse:
    proxy = raw.get("proxy") or {}
    return UserSettingsResponse(
        proxy_server=proxy.get("server"),
        proxy_username=proxy.get("username"),
        proxy_has_password=bool(proxy.get("password")),
        daily_limit=raw.get("daily_limit", settings.DEFAULT_DAILY_LIMIT),
    )

async def _get_stored_settings(user_id: str, redis: aioredis.Redis) -> dict:
    raw = await redis.get(RedisKeys.user_settings(user_id))
    return json.loads(raw) if raw else {}

@router.get("/", response_model=UserSettingsResponse)
async def get_settings_endpoint(
    user_id: str = "demo_user",
    redis: aioredis.Redis = Depends(get_redis),
) -> UserSettingsResponse:
    stored = await _get_stored_settings(user_id, redis)
    return _load_settings_from_dict(stored)

@router.put("/", response_model=UserSettingsResponse)
async def update_settings(
    body: UpdateSettingsRequest,
    user_id: str = "demo_user",
    redis: aioredis.Redis = Depends(get_redis),
) -> UserSettingsResponse:
    stored = await _get_stored_settings(user_id, redis)
    if body.proxy is not None:
        stored["proxy"] = body.proxy.model_dump(exclude_none=True)
    if body.daily_limit is not None:
        clamped = min(body.daily_limit, settings.MAX_DAILY_LIMIT)
        stored["daily_limit"] = clamped
        await redis.setex(name=f"settings:daily_limit:{user_id}", time=RedisKeys.RATE_LIMIT_TTL, value=str(clamped))
    await redis.set(RedisKeys.user_settings(user_id), json.dumps(stored))
    return _load_settings_from_dict(stored)

@router.delete("/proxy", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proxy(
    user_id: str = "demo_user",
    redis: aioredis.Redis = Depends(get_redis),
) -> None:
    stored = await _get_stored_settings(user_id, redis)
    if "proxy" in stored:
        del stored["proxy"]
        await redis.set(RedisKeys.user_settings(user_id), json.dumps(stored))
