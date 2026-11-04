"""The exact 422 a malformed server-scoped tool key produces, through the real error handler."""

from http import HTTPStatus
import json
from unittest.mock import patch

from fastapi import Request
import pytest

from app.core.exception_handlers import app_error_handler
from app.services.hil.preferences import MalformedToolKeyError, set_tool_override

from .conftest import USER_ID

HANDLERS_LOG = "app.core.exception_handlers.wide_log"
MALFORMED_KEY = "mcp:posthog"


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "PUT",
            "path": "/api/v1/approvals/preferences",
            "headers": [],
            "query_string": b"",
        }
    )


@pytest.mark.unit
class TestMalformedToolKeyEnvelope:
    async def test_the_refusal_renders_the_exact_client_envelope(self) -> None:
        with patch(HANDLERS_LOG):
            response = await app_error_handler(_request(), MalformedToolKeyError(MALFORMED_KEY))

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        body = json.loads(bytes(response.body))
        assert body["message"] == "Malformed tool key"
        assert body["why"] == "A server-scoped key reads mcp:<integration_id>:<tool name>."
        assert MALFORMED_KEY not in json.dumps(body)

    async def test_the_offending_key_is_recorded_on_the_wide_event_under_key(self) -> None:
        with patch(HANDLERS_LOG) as wide_log:
            await app_error_handler(_request(), MalformedToolKeyError(MALFORMED_KEY))

        wide_log.warning.assert_called_once_with(
            "app_error",
            error={
                "message": "Malformed tool key",
                "why": "A server-scoped key reads mcp:<integration_id>:<tool name>.",
                "key": MALFORMED_KEY,
            },
            status_code=422,
            path="/api/v1/approvals/preferences",
            method="PUT",
        )

    async def test_a_refused_override_raises_the_error_carrying_the_original_cause(self) -> None:
        with pytest.raises(MalformedToolKeyError) as refused:
            await set_tool_override(USER_ID, MALFORMED_KEY, True)

        assert refused.value.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert refused.value.message == "Malformed tool key"
        assert refused.value.meta == {"key": MALFORMED_KEY}
        assert isinstance(refused.value.__cause__, ValueError)
        assert str(refused.value.__cause__) == f"Malformed HIL tool key: {MALFORMED_KEY}"
