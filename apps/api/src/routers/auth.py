from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis
from core.database import get_db
from core.redis_client import RedisKeys, get_redis
from core.security import create_access_token, create_refresh_token, decode_token, verify_password
from models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["authentication"])

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"

class RefreshRequest(BaseModel):
    refresh_token: str

class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db), redis: aioredis.Redis = Depends(get_redis)) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == body.email, User.is_active == True))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    user_id = str(user.id)
    access_token = create_access_token(user_id)
    refresh_token = create_refresh_token(user_id)
    await redis.setex(name=RedisKeys.refresh_token(user_id), time=RedisKeys.REFRESH_TOKEN_TTL, value=refresh_token)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)

@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh_access_token(body: RefreshRequest, redis: aioredis.Redis = Depends(get_redis)) -> AccessTokenResponse:
    user_id = decode_token(body.refresh_token, expected_type="refresh")
    stored = await redis.get(RedisKeys.refresh_token(user_id))
    if stored != body.refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token is invalid or has been revoked")
    return AccessTokenResponse(access_token=create_access_token(user_id))

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, redis: aioredis.Redis = Depends(get_redis)) -> None:
    try:
        user_id = decode_token(body.refresh_token, expected_type="refresh")
        await redis.delete(RedisKeys.refresh_token(user_id))
    except HTTPException:
        pass
