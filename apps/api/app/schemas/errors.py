"""The one wire shape for every non-2xx body the API emits.

Every error path — ``AppError``, ``HTTPException`` (string or structured
``detail``), request validation, the unhandled-exception handler and the
middlewares that answer before a route runs — renders an ``ErrorEnvelope``
through ``error_response``. Clients narrow on ``code`` and display
``message``; nothing is nested under ``detail`` anywhere.
"""

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

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
        return cls._from_context(context, exc.message)

    @classmethod
    def from_http_exception(cls, exc: StarletteHTTPException) -> "ErrorEnvelope":
        """``detail`` is a string, or a mapping; one without a string ``message``
        renders under the status phrase, Starlette's own default for a missing detail."""
        if not isinstance(exc.detail, Mapping):
            return cls._from_context({}, str(exc.detail))
        message = exc.detail.get("message")
        if not isinstance(message, str):
            message = HTTPStatus(exc.status_code).phrase
        return cls._from_context(exc.detail, message)

    @classmethod
    def _from_context(cls, context: Mapping[str, Any], message: str) -> "ErrorEnvelope":
        fields = {**context, "message": message}
        # Clients narrow on a string code (web `getErrorCode`); anything else
        # is not one, so it is dropped rather than failing the error response.
        if not isinstance(fields.get("code"), str | None):
            del fields["code"]
        return cls.model_validate(fields)


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


def error_responses(descriptions: Mapping[int, str]) -> dict[int | str, dict[str, Any]]:
    """Route-level ``responses=`` that describe a status without losing the envelope as its body."""
    return {
        code: {"model": ErrorEnvelope, "description": text} for code, text in descriptions.items()
    }


# FastAPI documents a response ``model`` under the route's ``response_class``
# media type, so a ``text/html`` route has to spell out that its error bodies
# are still the JSON envelope (registered as a component by every other route).
_JSON_ENVELOPE_CONTENT: dict[str, Any] = {
    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}}
}
HTML_ROUTE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: _JSON_ENVELOPE_CONTENT,
    "4XX": _JSON_ENVELOPE_CONTENT,
    "5XX": _JSON_ENVELOPE_CONTENT,
}
