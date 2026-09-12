"""The one wire shape for every non-2xx body the API emits.

Every error path — ``AppError``, ``HTTPException`` (string or structured
``detail``), request validation, the unhandled-exception handler and the
middlewares that answer before a route runs — renders an ``ErrorEnvelope``
through ``error_response``. Clients narrow on ``code`` and display
``message``; nothing is nested under ``detail`` anywhere.
"""

from collections.abc import Mapping
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.utils.errors import AppError


class ValidationIssue(BaseModel):
    """One field-level failure from request validation (422)."""

    loc: list[str | int]
    msg: str
    type: str


class ErrorEnvelope(BaseModel):
    """Body of every 4xx/5xx response."""

    # AppError.meta and per-error context (toolkit, reset_time, checkout_url, ...)
    # flatten onto the envelope, so the key set is open beyond the fields below.
    model_config = ConfigDict(extra="allow")

    message: str = Field(description="Human-readable description of the failure.")
    code: str | None = Field(default=None, description="Machine-readable error code.")
    why: str | None = None
    fix: str | None = None
    errors: list[ValidationIssue] | None = Field(
        default=None, description="Field-level failures; present only on 422."
    )

    @classmethod
    def from_app_error(cls, exc: AppError) -> "ErrorEnvelope":
        context: dict[str, Any] = dict(exc.meta)
        if exc.why:
            context["why"] = exc.why
        if exc.fix:
            context["fix"] = exc.fix
        return cls(message=exc.message, **context)

    @classmethod
    def from_http_detail(cls, detail: object) -> "ErrorEnvelope":
        """``HTTPException.detail`` is a string, or a mapping carrying ``message``."""
        if isinstance(detail, Mapping):
            return cls.model_validate(dict(detail))
        return cls(message=str(detail))


def error_response(
    status_code: int,
    envelope: ErrorEnvelope,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Serialize an envelope as the body of a ``status_code`` response.

    Unset optional fields are omitted; a key an error explicitly carries as
    null (the 402's ``checkout_url``) stays present, because clients match on
    the full key set.
    """
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(exclude_unset=True),
        headers=dict(headers) if headers else None,
    )


# Declared once on every router mount so the OpenAPI schema (and the generated
# TypeScript) names the envelope for every non-2xx status, including the 422
# FastAPI would otherwise document as its own HTTPValidationError.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorEnvelope},
    "4XX": {"model": ErrorEnvelope},
    "5XX": {"model": ErrorEnvelope},
}
