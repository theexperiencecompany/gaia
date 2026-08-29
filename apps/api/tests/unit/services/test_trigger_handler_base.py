"""Tests for TriggerHandler.unregister in app.services.triggers.base."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from composio_client import APIStatusError, InternalServerError, PermissionDeniedError
import httpx
import pytest

from app.models.trigger_configs import GmailPollInboxConfig
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow, WorkflowStep
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


class TestQueueOneWorkflowDispatch:
    """The coalescing decision in _queue_one_workflow — the seam every
    integration webhook passes through, so no entry point can route around it."""

    @staticmethod
    def _workflow(trigger_name: str, trigger_data: object) -> Workflow:
        return Workflow(
            id="wf_disp",
            user_id="user_disp",
            title="Dispatch",
            prompt="p",
            steps=[WorkflowStep(title="s", description="d")],
            activated=True,
            trigger_config=TriggerConfig(
                type=TriggerType.INTEGRATION,
                enabled=True,
                trigger_name=trigger_name,
                trigger_data=trigger_data,
            ),
        )

    @staticmethod
    def _handler() -> _StubHandler:
        return _StubHandler()

    async def test_a_poll_trigger_event_is_buffered_with_its_own_window(self) -> None:
        workflow = self._workflow("gmail_poll_inbox", GmailPollInboxConfig(interval=15))
        buffer = AsyncMock(return_value=True)
        queue = AsyncMock()
        with (
            patch("app.services.triggers.base.buffer_trigger_event", buffer),
            patch(
                "app.services.triggers.base.WorkflowQueueService.queue_workflow_execution", queue
            ),
            patch(
                "app.services.triggers.base.tracked_todo_service.get_signal_matching_context",
                AsyncMock(return_value="todos!"),
            ),
        ):
            queued = await self._handler()._queue_one_workflow(
                workflow, {"payload": 1}, {}, "GMAIL_NEW_GMAIL_MESSAGE", "tid-1"
            )

        assert queued is True
        buffer.assert_awaited_once_with(
            "wf_disp",
            "user_disp",
            {"payload": 1},
            15 * 60,
            {"trigger_type": "integration", "tracked_todos_context": "todos!"},
        )
        queue.assert_not_awaited()

    async def test_a_failed_buffer_falls_back_to_immediate_dispatch(self) -> None:
        """Redis down must degrade to the old per-event path, never drop the event."""
        workflow = self._workflow("gmail_poll_inbox", GmailPollInboxConfig(interval=15))
        queue = AsyncMock()
        with (
            patch(
                "app.services.triggers.base.buffer_trigger_event",
                AsyncMock(return_value=False),
            ),
            patch(
                "app.services.triggers.base.WorkflowQueueService.queue_workflow_execution", queue
            ),
            patch(
                "app.services.triggers.base.tracked_todo_service.get_signal_matching_context",
                AsyncMock(return_value=""),
            ),
        ):
            queued = await self._handler()._queue_one_workflow(
                workflow, {"payload": 1}, {}, "GMAIL_NEW_GMAIL_MESSAGE", "tid-1"
            )

        assert queued is True
        queue.assert_awaited_once_with(
            "wf_disp",
            "user_disp",
            context={"trigger_type": "integration", "trigger_data": {"payload": 1}},
        )

    async def test_a_windowless_trigger_still_dispatches_immediately(self) -> None:
        """A meeting reminder held back for a window is a missed meeting."""
        workflow = self._workflow("calendar_event_starting_soon", None)
        buffer = AsyncMock(return_value=True)
        queue = AsyncMock()
        with (
            patch("app.services.triggers.base.buffer_trigger_event", buffer),
            patch(
                "app.services.triggers.base.WorkflowQueueService.queue_workflow_execution", queue
            ),
            patch(
                "app.services.triggers.base.tracked_todo_service.get_signal_matching_context",
                AsyncMock(return_value=""),
            ),
        ):
            queued = await self._handler()._queue_one_workflow(
                workflow, {"payload": 2}, {}, "CAL_EVT", None
            )

        assert queued is True
        buffer.assert_not_awaited()
        queue.assert_awaited_once_with(
            "wf_disp",
            "user_disp",
            context={"trigger_type": "integration", "trigger_data": {"payload": 2}},
        )

    async def test_any_positive_window_batches_even_one_second(self) -> None:
        """The boundary is zero, exactly: any positive window means the trigger
        declared a cadence and its events belong to a batch."""
        workflow = self._workflow("stub_trigger", None)
        buffer = AsyncMock(return_value=True)
        queue = AsyncMock()
        with (
            patch("app.services.triggers.base.coalesce_window_seconds", return_value=1),
            patch("app.services.triggers.base.buffer_trigger_event", buffer),
            patch(
                "app.services.triggers.base.WorkflowQueueService.queue_workflow_execution", queue
            ),
            patch(
                "app.services.triggers.base.tracked_todo_service.get_signal_matching_context",
                AsyncMock(return_value=""),
            ),
        ):
            queued = await self._handler()._queue_one_workflow(
                workflow, {"payload": 3}, {}, "EVT", None
            )

        assert queued is True
        buffer.assert_awaited_once()
        assert buffer.await_args.args[3] == 1
        queue.assert_not_awaited()
