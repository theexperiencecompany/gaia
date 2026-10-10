"""The exception handlers that turn every raised failure into the envelope.

Registered by register_exception_handlers on every FastAPI app this repo serves
— the main API and the embedding sidecar — so a second app cannot ship a
different error shape by omission.
"""

from typing import Any

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.utils import is_body_allowed_for_status_code
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.unhandled_errors import capture_unhandled_exception, internal_error_response
from app.schemas.errors import ErrorEnvelope, ValidationIssue, error_response
from app.utils.errors import AppError
from shared.py.wide_events import log as wide_log


async def app_error_handler(request: Request, exc: AppError) -> Response:
    """Convert AppError into a structured JSON response with wide event context.

    Emits an explicit error log so the wide-event final_level flips to ERROR and
    the Loki level/errors filters catch it; without it an AppError is visible
    only in Sentry.
    """
    wide_log.error(
        "app_error",
        error=exc.to_dict(),
        status_code=exc.status_code,
        path=request.url.path,
        method=request.method,
    )
    return error_response(exc.status_code, ErrorEnvelope.from_app_error(exc))


async def validation_error_handler(
    request: Request,  # noqa: ARG001 -- Starlette calls exception handlers as handler(conn, exc)
    exc: RequestValidationError,
) -> Response:
    """Log validation errors with field-level detail and return 422."""
    # Each entry is pydantic's ErrorDetails; the undeclared keys (input, ctx,
    # url) are ignored by the model.
    errors = [ValidationIssue.model_validate(err) for err in exc.errors()]
    wide_log.warning(
        "validation_failed",
        validation_errors=[issue.model_dump() for issue in errors],
        error_count=len(errors),
    )
    return error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorEnvelope(message="Request validation failed", code="validation_error", errors=errors),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    """Record the failure on the wide event, then render it as the envelope.

    Starlette's ExceptionMiddleware converts an HTTPException inside call_next,
    so LoggingMiddleware's except path never sees it. Preserves exc.headers
    (WWW-Authenticate on 401, Retry-After on 429) and drops the body for
    statuses that may not carry one (204/304).
    """
    failure: dict[str, Any] = {
        "status_code": exc.status_code,
        "detail": exc.detail,
        "path": request.url.path,
        "method": request.method,
    }
    # Only an explicit `raise ... from e` counts: __context__ is set by any
    # exception raised inside an except block and is usually unrelated.
    cause = exc.__cause__
    if cause is not None:
        failure["error_type"] = type(cause).__name__
        failure["error"] = str(cause)

    # Mirrors the status -> level mapping the logging middleware applies.
    record = wide_log.error if exc.status_code >= 500 else wide_log.warning
    record("http_exception", **failure)

    if not is_body_allowed_for_status_code(exc.status_code):
        return Response(status_code=exc.status_code, headers=exc.headers)
    return error_response(
        exc.status_code, ErrorEnvelope.from_http_exception(exc), headers=exc.headers
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    """Last-resort 500 envelope for a crash that escaped every middleware.

    Runs in ServerErrorMiddleware, OUTSIDE CORSMiddleware, so a browser cannot
    read the body it returns. UnhandledExceptionMiddleware sits inside CORS and
    converts crashes first; this only fires for the middlewares outside it.
    """
    capture_unhandled_exception(request, exc)
    return internal_error_response()


def register_exception_handlers(app: FastAPI) -> None:
    """Give app the one error envelope for every kind of raised failure.

    The decorator form, not add_exception_handler: the latter is typed
    Callable[[Request, Exception], ...] and rejects a handler that names the
    exception it is registered for.
    """
    app.exception_handler(AppError)(app_error_handler)
    app.exception_handler(RequestValidationError)(validation_error_handler)
    app.exception_handler(StarletteHTTPException)(http_exception_handler)
    app.exception_handler(Exception)(unhandled_exception_handler)
