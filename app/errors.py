"""Application errors and the single JSON error envelope used by every endpoint."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class. Services raise subclasses, handlers turn them into HTTP responses."""

    code = "INTERNAL_ERROR"
    http_status = 500

    def __init__(self, message: str, file_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.file_id = file_id


class InvalidRequest(AppError):
    code = "INVALID_REQUEST"
    http_status = 400


class FileNotFound(AppError):
    code = "FILE_NOT_FOUND"
    http_status = 404


class FileNotCompleted(AppError):
    code = "FILE_NOT_COMPLETED"
    http_status = 409


class FileTooLarge(AppError):
    code = "FILE_TOO_LARGE"
    http_status = 413


class UnsupportedFileType(AppError):
    code = "UNSUPPORTED_FILE_TYPE"
    http_status = 415


class UnprocessableFile(AppError):
    code = "UNPROCESSABLE_FILE"
    http_status = 422


def error_body(code: str, message: str, file_id: str | None = None) -> dict:
    error: dict = {"code": code, "message": message}
    if file_id:
        error["file_id"] = file_id
    return {"error": error}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status, content=error_body(exc.code, exc.message, exc.file_id)
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", []) if part != "body")
        message = f"Invalid request: {location or 'request'} {first.get('msg', 'is invalid')}."
        return JSONResponse(status_code=400, content=error_body("INVALID_REQUEST", message))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_body("INTERNAL_ERROR", "An unexpected error occurred."),
        )
