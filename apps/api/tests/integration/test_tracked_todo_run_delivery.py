"""A tracked todo's run delivers the executor's narrated result, once, or nothing.

Regression for the 2026-09-26 Telegram message "Dispatched the only actionable
step… Task in flight; result will land on its own": the run went through comms,
which handed off to the executor and wrote that acknowledgement before any work
happened; the worker delivered the acknowledgement, while the executor's real,
narrated result (comms had SILENCED it) was saved into a conversation that does
not exist and dropped. Unit tests mocked call_agent_silent and never saw it.

Real here: run_todo_on_executor, run_executor_background, finalize, deliver_result
and todo delivery. Faked: the two model calls (executor, comms narration), Redis,
and the outbound transport.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.background import (
    executor_runner as er,
    result_delivery as rd,
    session as sess,
    todo_run,
    todo_run_delivery as trd,
)
from app.agents.core.background.executor_runner import _ExecutorResult
from app.agents.core.background.session import TodoRun
from app.agents.core.background.todo_run import (
    TodoRunFailedError,
    TodoRunRequest,
    run_todo_on_executor,
)
from app.constants.agents import AgentTag
from app.constants.comms import SILENCE_KEYWORD
from app.constants.general import NEW_MESSAGE_BREAKER
from app.models.chat_models import ConversationSource
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType
from app.services.analytics_service import AnalyticsEvents

pytestmark = pytest.mark.integration

USER = AuthenticatedUser(user_id="507f1f77bcf86cd799439011", email="d@gaia.local")
TODO_ID = "6ab51f1ba7a1fcf0f00ab49a"
EXECUTOR_REPORT = "Checked staging. The deploy failed on migration 42; needs a rollback call."
NARRATED = f"Staging deploy failed on migration 42.{NEW_MESSAGE_BREAKER}Want me to roll it back?"


def _todo(*, notify_on_run: bool = True) -> TodoDocument:
    return TodoDocument(
        id=TODO_ID,
        user_id=USER.user_id,
        title="Watch the staging deploy",
        labels=["gaia-tracked"],
        notify_on_run=notify_on_run,
    )


@dataclass
class _Seams:
    narrate: AsyncMock
    send: AsyncMock
    activity: AsyncMock
    capture: MagicMock
    save_to_conversation: AsyncMock
    execute: AsyncMock


@contextmanager
def _seams(
    *,
    todo: TodoDocument,
    narrated: str = NARRATED,
    executor: _ExecutorResult | None = None,
) -> Iterator[_Seams]:
    seams = _Seams(
        narrate=AsyncMock(return_value=narrated),
        send=AsyncMock(return_value=ConversationSource.TELEGRAM),
        activity=AsyncMock(return_value=True),
        capture=MagicMock(),
        save_to_conversation=AsyncMock(),
        execute=AsyncMock(return_value=executor or _ExecutorResult(EXECUTOR_REPORT, "final")),
    )
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=todo)
    stream_manager = MagicMock()
    stream_manager.is_cancelled = AsyncMock(return_value=False)
    inbox = MagicMock()
    inbox.return_value.read = AsyncMock(return_value=[])
    with (
        patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=True)),
        patch.object(er, "_execute_executor", seams.execute),
        patch.object(er, "StreamManager", stream_manager),
        patch.object(er, "release_lock_if_owned", AsyncMock()),
        patch.object(er, "ExecutorInbox", inbox),
        patch("app.services.hil.bridge.flush_held_approval_cards", AsyncMock()),
        patch.object(rd, "update_messages", seams.save_to_conversation),
        patch.object(trd, "narrate_executor_result", seams.narrate),
        patch.object(trd, "deliver_result_to_platforms", seams.send),
        patch.object(trd, "todo_repository", repo),
        patch.object(trd.tracked_todo_service, "append_activity_entry", seams.activity),
        patch.object(trd, "capture_event", seams.capture),
    ):
        yield seams
    sess._sessions.clear()


def _request() -> TodoRunRequest:
    return TodoRunRequest(
        user=USER,
        todo_run=TodoRun(todo_id=TODO_ID, trigger_type=TriggerType.SCHEDULED_TODO),
        todo_title="Watch the staging deploy",
        task="Execute the following scheduled task: Watch the staging deploy",
        conversation_id="run-conv-1",
    )


def _activity(seams: _Seams) -> str:
    return seams.activity.await_args.kwargs["entry"]


class TestTheExecutorsResultIsWhatReachesTheUser:
    async def test_the_narrated_executor_result_is_sent_to_the_chat_app(self) -> None:
        with _seams(todo=_todo()) as seams:
            await run_todo_on_executor(_request())

        seams.send.assert_awaited_once()
        sent = seams.send.await_args.kwargs
        assert sent["notification_text"] == NARRATED
        assert sent["user_id"] == USER.user_id
        assert TODO_ID in sent["origin"]
        # Comms narrated the EXECUTOR's report, under the todo's delivery rules.
        narrated_from, _msg_type, _conversation, _user = seams.narrate.await_args.args
        assert narrated_from == EXECUTOR_REPORT
        preamble = seams.narrate.await_args.kwargs["preamble"]
        assert "Watch the staging deploy" in preamble
        assert f"<{AgentTag.DELIVERY_INSTRUCTIONS}>" in preamble

    async def test_the_run_conversation_is_never_written(self) -> None:
        """It has no transport and does not exist: a save there 404s and drops the result."""
        with _seams(todo=_todo()) as seams:
            await run_todo_on_executor(_request())

        seams.save_to_conversation.assert_not_awaited()

    async def test_the_executor_runs_the_brief_itself_in_background_mode(self) -> None:
        with _seams(todo=_todo()) as seams:
            await run_todo_on_executor(_request())

        task, configurable, run, _resume = seams.execute.await_args.args
        assert task == _request().task
        assert configurable["execution_mode"] == "background"
        assert configurable["active_todo_id"] == TODO_ID
        assert configurable["conversation_id"] == "run-conv-1"
        # The todo's title stands in for the user's words for the approval judge.
        assert "Tracked todo: Watch the staging deploy" in configurable["user_messages"]
        assert run.todo_run == TodoRun(todo_id=TODO_ID, trigger_type=TriggerType.SCHEDULED_TODO)

    async def test_the_outcome_is_recorded_and_captured(self) -> None:
        with _seams(todo=_todo()) as seams:
            await run_todo_on_executor(_request())

        entry = _activity(seams)
        assert "✓ run finished; result sent on telegram" in entry
        assert "Checked staging." in entry
        user_id, event, props = seams.capture.call_args.args
        assert (user_id, event) == (USER.user_id, AnalyticsEvents.TODO_RUN_RESULT_DELIVERED)
        assert props["outcome"] == "delivered"
        assert props["delivered"] is True
        assert props["platform"] == "telegram"


class TestNothingIsSentWhenNothingShouldBe:
    async def test_a_silenced_result_sends_nothing_and_says_why(self) -> None:
        silenced = f"{SILENCE_KEYWORD}: no-op wake, nothing changed{NEW_MESSAGE_BREAKER}"
        with _seams(todo=_todo(), narrated=silenced) as seams:
            await run_todo_on_executor(_request())

        seams.send.assert_not_awaited()
        assert "kept quiet: no-op wake, nothing changed" in _activity(seams)
        assert seams.capture.call_args.args[2]["outcome"] == "silenced"

    async def test_a_reaction_is_not_a_message_for_a_run_nobody_triggered(self) -> None:
        with _seams(todo=_todo(), narrated="REACT: 👍") as seams:
            await run_todo_on_executor(_request())

        seams.send.assert_not_awaited()
        assert seams.capture.call_args.args[2]["outcome"] == "invalid_directive"

    async def test_delivery_turned_off_during_the_run_is_honoured(self) -> None:
        """notify_on_run is read at the end: the prod run turned it off mid-run and still pinged."""
        with _seams(todo=_todo(notify_on_run=False)) as seams:
            await run_todo_on_executor(_request())

        seams.narrate.assert_not_awaited()
        seams.send.assert_not_awaited()
        assert "delivery is off for this todo" in _activity(seams)

    async def test_an_executor_error_raises_for_the_retry_ladder_and_sends_nothing(self) -> None:
        with (
            _seams(todo=_todo(), executor=_ExecutorResult("tool exploded", "error")) as seams,
            pytest.raises(TodoRunFailedError, match="tool exploded"),
        ):
            await run_todo_on_executor(_request())

        seams.narrate.assert_not_awaited()
        seams.send.assert_not_awaited()
        seams.activity.assert_not_awaited()
