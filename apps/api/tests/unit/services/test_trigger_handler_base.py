"""Tests for TriggerHandler.unregister in app.services.triggers.base."""

from collections.abc import Iterator
import sys
from typing import Any
from unittest.mock import MagicMock, patch

from composio_client import APIStatusError, InternalServerError, PermissionDeniedError
import httpx
import pytest

# Pre-populate the circular-import path with a stub so importing the base
# handler does not trigger the full workflow → trigger_service → triggers loop.
sys.modules.setdefault("app.services.workflow.queue_service", MagicMock())
sys.modules.setdefault("app.services.workflow.trigger_service", MagicMock())

from app.models.workflow_models import Workflow
from app.services.triggers.base import TriggerHandler


class _StubHandler(TriggerHandler):
    """Minimal concrete handler — only the inherited unregister is under test."""

    @property
    def trigger_names(self) -> list[str]:
        return ["stub_trigger"]

    @property
    def event_types(self) -> set[str]:
        return {"STUB_EVENT"}

    async def register(
        self, user_id: str, workflow_id: str, trigger_name: str, trigger_config: Any
    ) -> list[str]:
        return []

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: dict[str, Any]
    ) -> list[Workflow]:
        return []


def _api_status_error(
    status_code: int, body: str, error_cls: type[APIStatusError] = APIStatusError
) -> APIStatusError:
    """Build the exception the Composio client raises for a non-2xx delete.

    `error_cls` mirrors the SDK's own status→class mapping: 410 has no dedicated
    subclass and arrives as a bare APIStatusError. The message mirrors the SDK's
    format (`Error code: N - <body>`) — what reaches Sentry, and all a
    substring-based check would ever see.
    """
    response = httpx.Response(
        status_code, request=httpx.Request("DELETE", "https://backend.composio.dev/api/v3.1/x")
    )
    return error_cls(f"Error code: {status_code} - {body}", response=response, body=None)


_GONE_BODY = '{"error":{"message":"Trigger instance not found","error_code":"TriggerInstance_TriggerInstanceGone"}}'


@pytest.fixture
def composio_delete() -> Iterator[MagicMock]:
    """Patch get_composio_service and yield the mocked triggers.delete."""
    with patch("app.services.triggers.base.get_composio_service") as get_service:
        delete = MagicMock()
        get_service.return_value.composio.triggers.delete = delete
        yield delete


@pytest.mark.unit
class TestUnregister:
    async def test_no_trigger_ids_short_circuits(self, composio_delete: MagicMock) -> None:
        assert await _StubHandler().unregister("user-1", []) is True
        composio_delete.assert_not_called()

    async def test_successful_deletion_reports_success(self, composio_delete: MagicMock) -> None:
        assert await _StubHandler().unregister("user-1", ["ti_a", "ti_b"]) is True
        assert composio_delete.call_count == 2

    @pytest.mark.regression
    async def test_410_gone_is_treated_as_already_unregistered(
        self, composio_delete: MagicMock
    ) -> None:
        composio_delete.side_effect = _api_status_error(410, _GONE_BODY)

        assert await _StubHandler().unregister("user-1", ["ti_gone"]) is True

    @pytest.mark.regression
    async def test_410_gone_does_not_stop_remaining_deletions(
        self, composio_delete: MagicMock
    ) -> None:
        composio_delete.side_effect = [_api_status_error(410, _GONE_BODY), None]

        assert await _StubHandler().unregister("user-1", ["ti_gone", "ti_live"]) is True
        assert composio_delete.call_count == 2

    async def test_non_410_error_whose_body_mentions_410_is_a_failure(
        self, composio_delete: MagicMock
    ) -> None:
        """A real failure must not be swallowed just because "410" appears in its text.

        Composio echoes the trigger id back in the error body, so any id containing
        the digits 410 made a substring check report a live trigger as deleted.
        """
        composio_delete.side_effect = _api_status_error(
            500, '{"error":{"message":"upstream failed for ti_410abc"}}', InternalServerError
        )

        assert await _StubHandler().unregister("user-1", ["ti_410abc"]) is False

    async def test_other_api_status_error_reports_failure(self, composio_delete: MagicMock) -> None:
        composio_delete.side_effect = _api_status_error(
            403, '{"error":{"message":"Forbidden"}}', PermissionDeniedError
        )

        assert await _StubHandler().unregister("user-1", ["ti_a"]) is False

    async def test_non_http_exception_reports_failure(self, composio_delete: MagicMock) -> None:
        composio_delete.side_effect = ConnectionError("boom")

        assert await _StubHandler().unregister("user-1", ["ti_a"]) is False
