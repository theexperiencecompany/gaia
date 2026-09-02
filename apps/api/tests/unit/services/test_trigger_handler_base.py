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
from tests.helpers import captured_wide_event


class _StubHandler(TriggerHandler):
    """Minimal concrete handler — only the inherited unregister is under test."""

    @property
    def trigger_names(self) -> list[str]:
        return ["stub_trigger"]

    @property
    def event_types(self) -> set[str]:
        return {"STUB_EVENT"}

    async def register(
        self, user_id: str, owner_id: str, trigger_name: str, trigger_config: Any
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
                "app.services.triggers.base.get_signal_matching_context",
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
                "app.services.triggers.base.get_signal_matching_context",
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
                "app.services.triggers.base.get_signal_matching_context",
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
                "app.services.triggers.base.get_signal_matching_context",
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


class TestTodoDispatchHandoff:
    """The tap that makes a todo-only event survive.

    ``process_event`` returns early when no workflow matches, and that return is
    what drops the reply a todo has been waiting for. The hand-off has to happen
    before it.
    """

    @staticmethod
    def _handler():
        return _StubHandler()

    @staticmethod
    def _workflow() -> Workflow:
        return Workflow(
            id="wf_todo_tap",
            user_id="user-1",
            title="Tap",
            prompt="p",
            steps=[WorkflowStep(title="s", description="d")],
            activated=True,
            trigger_config=TriggerConfig(type=TriggerType.INTEGRATION, enabled=True),
        )

    async def _process(self, *, workflows, enqueue):
        handler = self._handler()
        handler.find_workflows = AsyncMock(return_value=workflows)
        with (
            patch("app.services.triggers.base.RedisPoolManager.get_pool", AsyncMock()),
            patch("app.services.triggers.base.enqueue_worker_job", enqueue),
            patch(
                "app.services.triggers.base.get_signal_matching_context",
                AsyncMock(return_value=""),
            ),
            patch(
                "app.services.triggers.base.WorkflowQueueService.queue_workflow_execution",
                AsyncMock(return_value=True),
            ),
        ):
            return await handler.process_event("TEST_EVENT", "tid-1", "user-1", {"id": "e1"})

    async def test_an_event_with_no_workflow_still_reaches_subscribed_todos(self):
        enqueue = AsyncMock()

        result = await self._process(workflows=[], enqueue=enqueue)

        assert result["status"] == "success"
        enqueue.assert_awaited_once()
        assert enqueue.await_args.args[1] == "dispatch_todo_subscriptions"

    async def test_the_handoff_carries_the_handlers_trigger_names_and_payload(self):
        enqueue = AsyncMock()

        await self._process(workflows=[], enqueue=enqueue)

        args = enqueue.await_args.args
        assert args[2] == self._handler().trigger_names
        assert args[3] == "tid-1"
        assert args[4] == "user-1"
        assert args[5] == {"id": "e1"}

    async def test_a_matched_workflow_does_not_suppress_the_todo_handoff(self):
        # Both consumers are independent; a workflow match must not hide a todo.
        enqueue = AsyncMock()

        await self._process(workflows=[self._workflow()], enqueue=enqueue)

        enqueue.assert_awaited_once()

    async def test_a_failed_handoff_does_not_take_the_workflow_dispatch_down(self):
        # Letting a subscription problem fail workflow queueing turns a small bug
        # into an outage.
        enqueue = AsyncMock(side_effect=RuntimeError("redis down"))

        result = await self._process(workflows=[self._workflow()], enqueue=enqueue)

        assert result["status"] == "success"
        assert "Queued 1 workflows" in result["message"]

    async def test_the_handoff_enqueues_on_the_real_pool_and_reports_queued(self):
        # The job must ride the pool `get_pool` returned, not some other value,
        # and a successful enqueue reports True back to process_event.
        handler = self._handler()
        pool = object()
        enqueue = AsyncMock()
        with (
            patch(
                "app.services.triggers.base.RedisPoolManager.get_pool",
                AsyncMock(return_value=pool),
            ),
            patch("app.services.triggers.base.enqueue_worker_job", enqueue),
        ):
            queued = await handler._queue_todo_dispatch("EVT", "tid-1", "user-1", {"id": "e1"})

        assert queued is True
        enqueue.assert_awaited_once_with(
            pool,
            "dispatch_todo_subscriptions",
            handler.trigger_names,
            "tid-1",
            "user-1",
            {"id": "e1"},
        )

    async def test_a_failed_enqueue_reports_not_queued_and_logs_the_context(self):
        # The swallow is only justified if the failure is visible on the wide
        # event with enough context to debug it — and it must return False.
        handler = self._handler()
        enqueue = AsyncMock(side_effect=RuntimeError("redis boom"))
        with (
            patch("app.services.triggers.base.RedisPoolManager.get_pool", AsyncMock()),
            patch("app.services.triggers.base.enqueue_worker_job", enqueue),
        ):
            async with captured_wide_event() as event:
                queued = await handler._queue_todo_dispatch("EVT", "tid-1", "user-1", {"id": "e1"})

        assert queued is False
        (error,) = event["errors"]
        assert error["msg"] == "trigger_todo_dispatch_enqueue_failed"
        assert error["event_type"] == "EVT"
        assert error["trigger_id"] == "tid-1"
        assert error["error"] == "redis boom"
        assert error["error_type"] == "RuntimeError"

    async def test_process_event_hands_the_real_event_type_to_the_dispatch(self):
        # process_event must pass its own event_type down — a None there would
        # strand the dispatch failure log with no way to tell which event broke.
        handler = self._handler()
        handler.find_workflows = AsyncMock(return_value=[])
        enqueue = AsyncMock(side_effect=RuntimeError("redis down"))
        with (
            patch("app.services.triggers.base.RedisPoolManager.get_pool", AsyncMock()),
            patch("app.services.triggers.base.enqueue_worker_job", enqueue),
            patch(
                "app.services.triggers.base.get_signal_matching_context",
                AsyncMock(return_value=""),
            ),
        ):
            async with captured_wide_event() as event:
                await handler.process_event("TEST_EVENT", "tid-1", "user-1", {"id": "e1"})

        (error,) = event["errors"]
        assert error["event_type"] == "TEST_EVENT"
