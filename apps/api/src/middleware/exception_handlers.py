from __future__ import annotations
import logging
import traceback
import uuid
from typing import Any
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

def _error_envelope(code: str, message: str, request_id: str, details: Any = None) -> dict:
    return {
        "success": False,
        "error": {"code": code, "message": message, "details": details},
        "request_id": request_id,
    }

def _extract_request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID", str(uuid.uuid4()))

def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = _extract_request_id(request)
        field_errors = [
            {"field": " -> ".join(str(loc) for loc in err["loc"]), "message": err["msg"], "type": err["type"]}
            for err in exc.errors()
        ]
        logger.warning("Validation error | request_id=%s | path=%s", request_id, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_envelope("VALIDATION_ERROR", "Request validation failed.", request_id, field_errors),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = _extract_request_id(request)
        logger.warning("HTTP exception | request_id=%s | status=%d | detail=%s", request_id, exc.status_code, exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_envelope("HTTP_ERROR", str(exc.detail), request_id),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        from core.config import settings
        request_id = _extract_request_id(request)
        tb = traceback.format_exc()
        logger.exception("Unhandled exception | request_id=%s | path=%s", request_id, request.url.path)
        details = None if settings.is_production else {"traceback": tb[-2000:]}
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_envelope("INTERNAL_ERROR", "An unexpected error occurred.", request_id, details),
        )
