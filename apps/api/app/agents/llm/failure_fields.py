"""Describe a failed model call on a log line by its shape, never by its message.

A provider's error text can quote the request, and a malformed structured reply's
quotes the model's output, so either carries a user's messages or memory into the logs.
"""

import re
from typing import TypedDict

from google.genai.errors import APIError as GeminiAPIError
import openai
from openrouter.errors import OpenRouterError

from app.db.repositories.llm_calls import ErrorFamily
from app.services.llm_metering import classify_error_family

#: A provider's code is an identifier (rate_limit_exceeded, 3040, RESOURCE_EXHAUSTED); anything else is dropped.
_PROVIDER_CODE = re.compile(r"[\w.:-]{1,64}")


class FailedCallFields(TypedDict):
    """The log fields of one failed model call.

    error_type is also what stops the log facade stamping the message of an
    exception still in flight.
    """

    error_type: str
    error_family: ErrorFamily
    http_status: int | None
    provider_code: str | None


def failed_call_fields(error: BaseException) -> FailedCallFields:
    """Return what a log line may say about a failed model call."""
    http_status: int | None = None
    code: object = None
    if isinstance(error, GeminiAPIError):
        http_status, code = error.code, error.status
    elif isinstance(error, openai.APIStatusError):
        http_status, code = error.status_code, error.code
    elif isinstance(error, OpenRouterError):
        http_status = error.status_code
    return FailedCallFields(
        error_type=type(error).__name__,
        error_family=classify_error_family(error),
        http_status=http_status,
        provider_code=str(code)
        if code is not None and _PROVIDER_CODE.fullmatch(str(code))
        else None,
    )
