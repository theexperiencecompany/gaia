"""failed_call_fields describes a failed model call by type, family, status and code, never its message."""

from google.genai.errors import ClientError as GeminiClientError
import httpx
from openai import APIConnectionError, BadRequestError, RateLimitError
from openrouter.errors import TooManyRequestsResponseError
import pytest

from app.agents.llm.failure_fields import FailedCallFields, failed_call_fields

_REQUEST = httpx.Request("POST", "https://provider.test")
USER_TEXT = "my sister Asha is moving to Lisbon in March"


def _openai_400(code: object) -> BadRequestError:
    return BadRequestError(
        f"Invalid request: {USER_TEXT!r}",
        response=httpx.Response(400, request=_REQUEST),
        body={"message": USER_TEXT, "code": code},
    )


def _openrouter_429() -> TooManyRequestsResponseError:
    """Build OpenRouter's rate-limit error without the response model its constructor parses."""
    error = TooManyRequestsResponseError.__new__(TooManyRequestsResponseError)
    error.message = USER_TEXT
    error.status_code = 429
    return error


@pytest.mark.parametrize(
    ("error", "fields"),
    [
        (
            _openai_400("context_length_exceeded"),
            FailedCallFields(
                error_type="BadRequestError",
                error_family="invalid_request",
                http_status=400,
                provider_code="context_length_exceeded",
            ),
        ),
        (
            # Workers AI sends numeric codes.
            _openai_400(3040),
            FailedCallFields(
                error_type="BadRequestError",
                error_family="invalid_request",
                http_status=400,
                provider_code="3040",
            ),
        ),
        (
            RateLimitError(
                "rate limiting", response=httpx.Response(429, request=_REQUEST), body=None
            ),
            FailedCallFields(
                error_type="RateLimitError",
                error_family="rate_limit",
                http_status=429,
                provider_code=None,
            ),
        ),
        (
            GeminiClientError(
                429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": USER_TEXT}}
            ),
            FailedCallFields(
                error_type="ClientError",
                error_family="other",
                http_status=429,
                provider_code="RESOURCE_EXHAUSTED",
            ),
        ),
        (
            _openrouter_429(),
            FailedCallFields(
                error_type="TooManyRequestsResponseError",
                error_family="rate_limit",
                http_status=429,
                provider_code=None,
            ),
        ),
        (
            APIConnectionError(request=_REQUEST),
            FailedCallFields(
                error_type="APIConnectionError",
                error_family="provider_unavailable",
                http_status=None,
                provider_code=None,
            ),
        ),
        (
            ConnectionError(USER_TEXT),
            FailedCallFields(
                error_type="ConnectionError",
                error_family="provider_unavailable",
                http_status=None,
                provider_code=None,
            ),
        ),
    ],
    ids=[
        "openai_wire_status_and_code",
        "numeric_provider_code",
        "openai_wire_without_a_code",
        "gemini_status_and_code",
        "openrouter_status",
        "sdk_error_without_a_response",
        "stdlib_error",
    ],
)
def test_a_failed_call_is_described_by_its_shape(
    error: BaseException, fields: FailedCallFields
) -> None:
    assert failed_call_fields(error) == fields


@pytest.mark.parametrize("code", [USER_TEXT, f"quota exceeded for {USER_TEXT}", "", "x" * 65])
def test_a_provider_code_that_is_not_an_identifier_is_dropped(code: str) -> None:
    assert failed_call_fields(_openai_400(code))["provider_code"] is None
