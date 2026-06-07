"""
OutreachOS API — Educational Portfolio Project
================================================
Developed by: Talha Dogan
Purpose:      Educational demonstration of full-stack async architecture
Stack:        FastAPI + Celery + Redis + Playwright + PostgreSQL

DISCLAIMER:
    This software is developed strictly for educational and portfolio purposes.
    The developer (Talha Dogan) bears no legal responsibility for misuse.
    Automating interactions on third-party platforms may violate their Terms of Service.
    All consequences of use are the sole responsibility of the end user.
    This is a learning project only.
"""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from core.config import settings
from core.database import dispose_engine, get_engine
from core.redis_client import close_redis_pool, get_redis_pool
from middleware.exception_handlers import register_exception_handlers
from routers import auth, websocket
from routers import settings as settings_router
from routers import tasks

logging.basicConfig(
    level=logging.DEBUG if not settings.is_production else logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-8s | %(message)s",
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting OutreachOS API (env=%s)", settings.ENVIRONMENT)
    get_engine()
    get_redis_pool()
    logger.info("Database engine and Redis pool ready")
    yield
    logger.info("Shutting down — disposing resources")
    await dispose_engine()
    await close_redis_pool()
    logger.info("Shutdown complete")

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_TITLE,
        version=settings.APP_VERSION,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    register_exception_handlers(app)
    api_prefix = "/api/v1"
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(settings_router.router, prefix=api_prefix)
    app.include_router(tasks.router, prefix=api_prefix)
    app.include_router(websocket.router)
    return app

app = create_app()

@app.get("/health", include_in_schema=False)
async def health_check() -> JSONResponse:
    return JSONResponse(content={"status": "ok", "version": settings.APP_VERSION})

@app.get("/ready", include_in_schema=False)
async def readiness_check() -> JSONResponse:
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError
    checks: dict[str, bool] = {}
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = True
    except SQLAlchemyError:
        checks["postgres"] = False
    try:
        redis = get_redis_pool()
        await redis.ping()
        checks["redis"] = True
    except Exception:
        checks["redis"] = False
    all_healthy = all(checks.values())
    return JSONResponse(
        status_code=200 if all_healthy else 503,
        content={"status": "ready" if all_healthy else "degraded", "checks": checks},
    )

