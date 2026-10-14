"""The one wire shape for every non-2xx body the API emits.

Every error path — ``AppError``, ``HTTPException`` (string, list or structured
``detail``), request validation, the unhandled-exception handler and the
middlewares that answer before a route runs — renders an ``ErrorEnvelope``
through ``error_response``. Clients narrow on ``code`` and display
``message``; nothing is nested under ``detail`` anywhere.

``error_response`` is total by construction: an exception handler that raises
produces a bare plaintext 500 with no CORS headers, which is the one failure
mode this module exists to prevent.
"""

from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any

from fastapi.responses import UJSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.utils.errors import AppError

#: Reason phrases by status, as a lookup rather than ``HTTPStatus(code)`` —
#: which raises ``ValueError`` on the non-standard codes the Composio proxy
#: deliberately forwards from upstream providers.
_STATUS_PHRASES: dict[int, str] = {status.value: status.phrase for status in HTTPStatus}
_UNKNOWN_STATUS_PHRASE = "Error"

#: Declared envelope fields whose type an arbitrary context mapping could
#: violate. A wrong type here would make ``model_validate`` raise inside an
#: exception handler, so the key is dropped instead.
_STRING_FIELDS = ("code", "why", "fix")


class ValidationIssue(BaseModel):
    """One field-level failure from request validation (422)."""

    loc: list[str | int]
    msg: str
    type: str


class ErrorEnvelope(BaseModel):
    """Body of every 4xx/5xx response."""

    # AppError.public and per-error context (toolkit, reset_time, checkout_url,
    # ...) flatten onto the envelope, so the key set is open beyond the fields
    # below. AppError.meta is NOT among them — it is wide-event context.
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
        """Render the client-facing half of an AppError; ``meta`` stays internal."""
        context: dict[str, Any] = dict(exc.public)
        if exc.code:
            context["code"] = exc.code
        if exc.why:
            context["why"] = exc.why
        if exc.fix:
            context["fix"] = exc.fix
        return cls._from_context(context, exc.message)

    @classmethod
    def from_http_exception(cls, exc: StarletteHTTPException) -> "ErrorEnvelope":
        """``detail`` is a string, a list of validation issues, or a mapping.

        A mapping without a string ``message`` renders under the status phrase,
        Starlette's own default for a missing detail.
        """
        phrase = _STATUS_PHRASES.get(exc.status_code, _UNKNOWN_STATUS_PHRASE)
        # Starlette annotates `detail` as a string; FastAPI and every caller in
        # this repo put whatever they like there, so narrow from the truth.
        detail: object = exc.detail
        if isinstance(detail, Mapping):
            message = detail.get("message")
            if not isinstance(message, str):
                message = phrase
            return cls._from_context(detail, message)
        if isinstance(detail, Sequence) and not isinstance(detail, str | bytes):
            return cls._from_context({"errors": [_as_issue(item) for item in detail]}, phrase)
        return cls._from_context({}, str(detail))

    @classmethod
    def _from_context(cls, context: Mapping[str, Any], message: str) -> "ErrorEnvelope":
        """Build the envelope from an arbitrary mapping without ever raising."""
        fields = {**context, "message": message}
        # Clients narrow on a string code (web `getErrorCode`); anything else
        # is not one, so it is dropped rather than failing the error response.
        for name in _STRING_FIELDS:
            if not isinstance(fields.get(name), str | None):
                del fields[name]
        errors = fields.get("errors")
        if errors is not None:
            if isinstance(errors, Sequence) and not isinstance(errors, str | bytes):
                fields["errors"] = [_as_issue(item) for item in errors]
            else:
                del fields["errors"]
        return cls.model_validate(fields)


def _as_issue(item: object) -> ValidationIssue:
    """One entry of a list ``detail`` as a validation issue.

    FastAPI's own validation errors are ``{loc, msg, type}`` mappings; anything
    else a caller put in the list is surfaced as its own message rather than
    rendered as a Python repr, which is what a plain ``str(detail)`` produced.
    """
    if isinstance(item, ValidationIssue):
        return item
    if isinstance(item, Mapping):
        loc = item.get("loc")
        msg = item.get("msg")
        type_ = item.get("type")
        if isinstance(loc, Sequence) and not isinstance(loc, str | bytes):
            return ValidationIssue(
                loc=[part if isinstance(part, int) else str(part) for part in loc],
                msg=str(msg) if msg is not None else "",
                type=str(type_) if type_ is not None else "value_error",
            )
    return ValidationIssue(loc=[], msg=str(item), type="value_error")


def error_response(
    status_code: int,
    envelope: ErrorEnvelope,
    headers: Mapping[str, str] | None = None,
) -> UJSONResponse:
    """Serialize an envelope as the body of a ``status_code`` response.

    ``UJSONResponse`` is the app's ``default_response_class``, so success and
    failure bodies go through one serializer and cannot drift. The dump is in
    JSON mode: an error is free to carry a datetime or a UUID, and a non-JSON
    type must not turn the response into a bare plaintext 500.

    Unset optional fields are omitted; a key an error explicitly carries as
    null (the 402's ``checkout_url``) stays present, because clients match on
    the full key set.
    """
    return UJSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode="json", exclude_unset=True),
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
