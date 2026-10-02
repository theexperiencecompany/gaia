"""A tracked todo's run delivers the executor's narrated result, once, or nothing.

Regression for the 2026-09-26 Telegram message "Dispatched the only actionable
step… Task in flight; result will land on its own": the run went through comms,
which handed off to the executor and wrote that acknowledgement before any work
happened; the worker delivered the acknowledgement, while the executor's real,
narrated result (comms had SILENCED it) was saved into a conversation that does
not exist and dropped. Unit tests mocked call_agent_silent and never saw it.

Real here: run_todo_on_executor, run_executor_background, finalize, deliver_result,
todo delivery and the activity entry. Faked: the two model calls (executor, comms
narration), Redis, the activity store and the outbound transport.
"""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from arq import Retry
from pymongo.errors import PyMongoError
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.agents.core.background import (
    executor_runner as er,
    result_delivery as rd,
    session as sess,
    todo_run,
    todo_run_delivery as trd,
)
from app.agents.core.background.executor_queue import build_lock_value
from app.agents.core.background.executor_runner import _ExecutorResult
from app.agents.core.background.session import RunKind, TodoRun, get_session
from app.agents.core.background.todo_run import (
    TODO_EXECUTOR_TASK_NAME,
    TodoRunFailedError,
    TodoRunRequest,
    run_todo_on_executor,
)
from app.agents.prompts.comms_prompts import tracked_todo_delivery_note
from app.constants import todos as todo_constants
from app.constants.agents import AgentTag
from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.log_tags import LogTag
from app.constants.todos import TodoActivityEvent
from app.models.chat_models import ConversationSource
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType
from app.services import todo_activity
from app.services.analytics_service import AnalyticsEvents
from app.utils.background_tasks import spawn_background_task
from app.workers.tasks import tracked_todo_tasks
from tests.helpers import WideEventRecorder, captured_wide_event

pytestmark = pytest.mark.unit

USER = AuthenticatedUser(user_id="507f1f77bcf86cd799439011", email="d@gaia.local")
TODO_ID = "6ab51f1ba7a1fcf0f00ab49a"
# The finish job loads the user afresh; a distinct object shows which one it used.
JOB_USER = USER.model_copy()
EXECUTOR_REPORT = "Checked staging. The deploy failed on migration 42; needs a rollback call."
NARRATED = f"Staging deploy failed on migration 42.{NEW_MESSAGE_BREAKER}Want me to roll it back?"


def _todo(*, notify_on_run: bool = True) -> TodoDocument:
    return TodoDocument(
        id=TODO_ID,
        user_id=USER.user_id,
        title="Watch the staging deploy",
        labels=["gaia-tracked"],
        notify_on_run=notify_on_run,
        canvas_content="## Key Details\n- Tell me when a deploy fails.\n\n## Current State\n- green\n",
    )


@dataclass
class _Seams:
    narrate: AsyncMock
    send: AsyncMock
    activity: AsyncMock
    capture: MagicMock
    save_to_conversation: AsyncMock
    execute: AsyncMock
    lock: AsyncMock
    spawn: MagicMock
    repo: MagicMock
    enqueue: AsyncMock
    pool: MagicMock
    load_user: AsyncMock


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
        lock=AsyncMock(return_value=True),
        spawn=MagicMock(side_effect=spawn_background_task),
        repo=MagicMock(get_by_id=AsyncMock(return_value=todo)),
        enqueue=AsyncMock(),
        pool=MagicMock(),
        load_user=AsyncMock(return_value=JOB_USER),
    )
    stream_manager = MagicMock()
    stream_manager.is_cancelled = AsyncMock(return_value=False)
    inbox = MagicMock()
    inbox.return_value.read = AsyncMock(return_value=[])
    with (
        patch.object(todo_run, "try_acquire_lock", seams.lock),
        patch.object(todo_run, "spawn_background_task", seams.spawn),
        patch.object(er, "_execute_executor", seams.execute),
        patch.object(er, "StreamManager", stream_manager),
        patch.object(er, "release_lock_if_owned", AsyncMock()),
        patch.object(er, "ExecutorInbox", inbox),
        patch("app.services.hil.bridge.flush_held_approval_cards", AsyncMock()),
        patch.object(rd, "update_messages", seams.save_to_conversation),
        patch.object(trd, "narrate_executor_result", seams.narrate),
        patch.object(trd, "deliver_result_to_platforms", seams.send),
        patch.object(trd, "todo_repository", seams.repo),
        patch.object(todo_activity, "append_activity", seams.activity),
        patch.object(trd, "capture_event", seams.capture),
        patch.object(trd, "enqueue_worker_job", seams.enqueue),
        patch.object(
            trd, "RedisPoolManager", MagicMock(get_pool=AsyncMock(return_value=seams.pool))
        ),
        patch.object(tracked_todo_tasks, "load_user_context", seams.load_user),
    ):
        yield seams
    sess._sessions.clear()


def _no_backoff() -> AbstractContextManager[AsyncMock]:
    """Skip the Mongo retry's backoff sleeps; the attempts themselves still run."""
    # By name: the policy's module is newer than the regression lane's base.
    return patch("app.db.mongodb.retry.TRANSIENT_MONGO_RETRY.sleep", AsyncMock())


def _request() -> TodoRunRequest:
    return TodoRunRequest(
        user=USER,
        todo_run=TodoRun(todo_id=TODO_ID, trigger_type=TriggerType.SCHEDULED_TODO),
        todo_title="Watch the staging deploy",
        task="Execute the following scheduled task: Watch the staging deploy",
        conversation_id="run-conv-1",
    )


def _activity(seams: _Seams) -> str:
    """Return the run's finish entry on the todo's timeline, after its run id."""
    todo_id, user_id, entry = seams.activity.await_args.args
    assert (todo_id, user_id) == (TODO_ID, USER.user_id)
    return entry.split(f"[{TodoActivityEvent.RUN_FINISHED.value}] run ", 1)[1].split(": ", 1)[1]


class TestTheExecutorsResultIsWhatReachesTheUser:
    async def test_the_narrated_executor_result_is_sent_to_the_chat_app(self) -> None:
        with _seams(todo=_todo()) as seams:
            await run_todo_on_executor(_request())

        seams.send.assert_awaited_once()
        sent = seams.send.await_args.kwargs
        assert sent["notification_text"] == NARRATED
        assert sent["user_id"] == USER.user_id
        assert (sent["user"].user_id, sent["user"].email) == (USER.user_id, USER.email)
        assert sent["origin"] == f'tracked todo "Watch the staging deploy" (id {TODO_ID})'
        # Comms narrated the EXECUTOR's report, in the run's conversation, under
        # the todo's delivery rules.
        narrated_from, msg_type, conversation_id, user = seams.narrate.await_args.args
        assert (narrated_from, msg_type, conversation_id) == (
            EXECUTOR_REPORT,
            "result",
            "run-conv-1",
        )
        assert user.user_id == USER.user_id
        assert seams.narrate.await_args.kwargs == {
            "preamble": tracked_todo_delivery_note(
                "Watch the staging deploy", "- Tell me when a deploy fails."
            )
        }
        assert f"<{AgentTag.DELIVERY_INSTRUCTIONS}>" in seams.narrate.await_args.kwargs["preamble"]
        seams.repo.get_by_id.assert_awaited_once_with(TODO_ID)

    @pytest.mark.regression
    async def test_a_silence_bubble_after_the_message_never_reaches_the_chat_app(self) -> None:
        """Live on Telegram: 7 of 12 deliveries carried the raw <SILENCE> tag after the message."""
        message = "Your passport expires in 13 days. Please book your renewal appointment."
        narrated = f"{message}{NEW_MESSAGE_BREAKER}<SILENCE>Within the 30-day threshold.</SILENCE>"
        with _seams(todo=_todo(), narrated=narrated) as seams:
            await run_todo_on_executor(_request())

        assert seams.send.await_args.kwargs["notification_text"] == message

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
        assert configurable["stream_id"] == run.stream_id
        # The todo's title stands in for the user's words for the approval judge.
        assert "Tracked todo: Watch the staging deploy" in configurable["user_messages"]
        assert run.todo_run == TodoRun(todo_id=TODO_ID, trigger_type=TriggerType.SCHEDULED_TODO)
        assert (run.kind, run.conversation_id, run.user_message_id) == (
            RunKind.LIVE,
            "run-conv-1",
            None,
        )
        assert run.stream_id and run.task_id and run.t_dispatch_perf is not None

    async def test_the_run_holds_the_conversations_executor_lock_under_its_own_ids(self) -> None:
        live: list[bool] = []

        async def execute(task, configurable, run, resume):
            # The stream's session exists, marked spawned, while the executor runs.
            session = get_session(run.stream_id)
            live.append(session is not None and session.executor_spawned)
            return _ExecutorResult(EXECUTOR_REPORT, "final")

        with _seams(todo=_todo()) as seams:
            seams.execute.side_effect = execute
            async with captured_wide_event() as event:
                await run_todo_on_executor(_request())
            run = seams.execute.await_args.args[2]
            # Registered up front, never auto-created mid-run as an ordering gap.
            assert not any(
                "Implicit session creation" in w["msg"] for w in event.get("warnings", [])
            )
            # ...and is dropped once the run is over.
            assert get_session(run.stream_id) is None

        assert live == [True]
        seams.lock.assert_awaited_once_with(
            "executor:busy:run-conv-1", build_lock_value(run.stream_id, run.task_id)
        )
        assert seams.spawn.call_args.kwargs["name"] == TODO_EXECUTOR_TASK_NAME

    async def test_every_run_gets_its_own_stream_and_task(self) -> None:
        with _seams(todo=_todo()) as seams:
            await run_todo_on_executor(_request())
            await run_todo_on_executor(_request())

        first, second = (c.args[2] for c in seams.execute.await_args_list)
        assert first.stream_id != second.stream_id
        assert first.task_id != second.task_id

    async def test_the_outcome_is_recorded_and_captured(self) -> None:
        with _seams(todo=_todo()) as seams:
            await run_todo_on_executor(_request())

        entry = _activity(seams)
        assert entry.startswith("result sent on telegram (summary='Checked staging.")
        user_id, event, props = seams.capture.call_args.args
        assert (user_id, event) == (USER.user_id, AnalyticsEvents.TODO_RUN_RESULT_DELIVERED)
        assert props == {
            "outcome": "delivered",
            "delivered": True,
            "platform": "telegram",
            "trigger_type": TriggerType.SCHEDULED_TODO.value,
            "recurring": False,
        }


class TestNothingIsSentWhenNothingShouldBe:
    async def test_a_silenced_result_sends_nothing_and_says_why(self) -> None:
        silenced = f"<SILENCE>no-op wake, nothing changed</SILENCE>{NEW_MESSAGE_BREAKER}"
        with _seams(todo=_todo(), narrated=silenced) as seams:
            await run_todo_on_executor(_request())

        seams.send.assert_not_awaited()
        assert _activity(seams).startswith("kept quiet: no-op wake, nothing changed (summary=")
        assert seams.capture.call_args.args[2]["outcome"] == "silenced"

    async def test_a_reaction_is_not_a_message_for_a_run_nobody_triggered(self) -> None:
        with _seams(todo=_todo(), narrated="<EMOJI>👍</EMOJI>") as seams:
            await run_todo_on_executor(_request())

        seams.send.assert_not_awaited()
        assert seams.capture.call_args.args[2]["outcome"] == "invalid_directive"
        assert "result not sent: the write-up was a reaction" in _activity(seams)

    async def test_delivery_turned_off_during_the_run_is_honoured(self) -> None:
        """notify_on_run is read at the end: the prod run turned it off mid-run and still pinged."""
        with _seams(todo=_todo(notify_on_run=False)) as seams:
            await run_todo_on_executor(_request())

        seams.narrate.assert_not_awaited()
        seams.send.assert_not_awaited()
        assert _activity(seams).startswith(
            "result not sent: delivery is off for this todo (summary="
        )
        assert seams.capture.call_args.args[2]["outcome"] == "notify_off"

    async def test_an_executor_error_raises_for_the_retry_ladder_and_sends_nothing(self) -> None:
        with (
            _seams(todo=_todo(), executor=_ExecutorResult("tool exploded", "error")) as seams,
            pytest.raises(TodoRunFailedError, match="tool exploded"),
        ):
            await run_todo_on_executor(_request())

        seams.narrate.assert_not_awaited()
        seams.send.assert_not_awaited()
        seams.activity.assert_not_awaited()


class TestAFinishedRunIsNeverRunAgainForItsDelivery:
    """The work is done, so a store failure is retried as delivery, never as the todo."""

    async def test_a_record_write_that_fails_once_is_retried_into_one_entry(self) -> None:
        written: list[str] = []
        outage = [PyMongoError("primary stepped down")]

        async def store(todo_id: str, user_id: str, entry: str, *, once: str) -> bool:
            if outage:
                raise outage.pop()
            assert once in entry
            written.append(entry)
            return True

        with _seams(todo=_todo()) as seams, _no_backoff():
            seams.activity.side_effect = store
            await run_todo_on_executor(_request())

        [entry] = written
        assert "result sent on telegram (summary=" in entry
        seams.send.assert_awaited_once()
        seams.enqueue.assert_not_awaited()

    @pytest.mark.regression
    async def test_a_todo_read_that_fails_once_is_retried_and_the_result_still_delivered(
        self,
    ) -> None:
        """Regression: a failed read of the todo dropped the finished run's message and entry."""
        with _seams(todo=_todo()) as seams, _no_backoff():
            seams.repo.get_by_id.side_effect = [PyMongoError("primary stepped down"), _todo()]
            await run_todo_on_executor(_request())

        seams.send.assert_awaited_once()
        assert _activity(seams).startswith("result sent on telegram (summary=")

    async def test_a_read_that_keeps_failing_is_delivered_by_the_runs_job(self) -> None:
        with _seams(todo=_todo()) as seams, _no_backoff():
            seams.repo.get_by_id.side_effect = PyMongoError("primary stepped down")
            await run_todo_on_executor(_request())
            seams.send.assert_not_awaited()
            undone = _queued(seams, "todo_run_result_not_delivered")

            seams.repo.get_by_id.side_effect = None
            await tracked_todo_tasks.finish_tracked_todo_run({"job_try": 2}, undone)

        seams.send.assert_awaited_once()
        assert seams.send.await_args.kwargs["user"] is JOB_USER
        seams.load_user.assert_awaited_once_with(USER.user_id)
        assert _activity(seams).startswith("result sent on telegram (summary=")
        assert seams.execute.await_count == 1

    async def test_an_entry_that_keeps_failing_is_written_by_its_job_without_a_second_send(
        self,
    ) -> None:
        with _seams(todo=_todo()) as seams, _no_backoff():
            seams.activity.side_effect = PyMongoError("primary stepped down")
            await run_todo_on_executor(_request())
            undone = _queued(seams, "todo_run_result_not_recorded")

            seams.activity.side_effect = None
            await tracked_todo_tasks.finish_tracked_todo_run({"job_try": 1}, undone)

        seams.send.assert_awaited_once()
        assert _activity(seams).startswith("result sent on telegram (summary=")

    async def test_a_job_that_sends_but_cannot_record_hands_the_entry_on(self) -> None:
        """A replay of the sending job would send again; the entry gets a job of its own."""
        with _seams(todo=_todo()) as seams, _no_backoff():
            seams.activity.side_effect = PyMongoError("primary stepped down")
            await tracked_todo_tasks.finish_tracked_todo_run({"job_try": 1}, _undelivered())

        seams.send.assert_awaited_once()
        undone = _queued(seams, "todo_run_result_not_recorded")
        assert "result sent on telegram (summary=" in (undone.finish_entry or "")

    async def test_a_job_for_a_run_already_finished_sends_nothing(self) -> None:
        marker = f"[{TodoActivityEvent.RUN_FINISHED.value}] run run-1:"
        todo = _todo().model_copy(update={"activity_content": f"- t {marker} result sent"})
        with _seams(todo=todo) as seams:
            await tracked_todo_tasks.finish_tracked_todo_run({"job_try": 1}, _undelivered())

        seams.send.assert_not_awaited()
        seams.activity.assert_not_awaited()

    async def test_a_job_still_failing_retries_then_gives_up_loudly(self) -> None:
        recorder = WideEventRecorder()
        with (
            _seams(todo=_todo()) as seams,
            _no_backoff(),
            patch("shared.py.wide_events._loguru", recorder),
        ):
            seams.repo.get_by_id.side_effect = PyMongoError("primary stepped down")
            with pytest.raises(Retry) as retry:
                await tracked_todo_tasks.finish_tracked_todo_run({"job_try": 4}, _undelivered())
            last_try = todo_constants.TODO_RUN_FINISH_MAX_TRIES
            async with captured_wide_event("finish") as event:
                await tracked_todo_tasks.finish_tracked_todo_run(
                    {"job_try": last_try}, _undelivered()
                )

        assert retry.value.defer_score == 8 * 60 * 1000
        seams.send.assert_not_awaited()
        assert event["todo_id"] == TODO_ID
        _assert_failed_loudly(
            event, "todo_run_result_not_delivered", f"still failing after {last_try} tries"
        )

    async def test_a_handoff_redis_refuses_fails_loudly(self) -> None:
        recorder = WideEventRecorder()
        with (
            _seams(todo=_todo()) as seams,
            _no_backoff(),
            patch("shared.py.wide_events._loguru", recorder),
        ):
            seams.repo.get_by_id.side_effect = PyMongoError("primary stepped down")
            seams.enqueue.side_effect = RedisConnectionError("redis down")
            await run_todo_on_executor(_request())

        event = recorder.event("executor_run")
        _assert_failed_loudly(event, "todo_run_result_not_delivered", "ConnectionError: redis down")
        [store_failure] = event["warnings"]
        assert (store_failure["error"], store_failure["error_type"]) == (
            "primary stepped down",
            "PyMongoError",
        )


def _undelivered() -> "trd.FinishedTodoRun":
    return trd.FinishedTodoRun(
        run_id="run-1",
        todo_id=TODO_ID,
        user_id=USER.user_id,
        conversation_id="run-conv-1",
        trigger_type=TriggerType.SCHEDULED_TODO,
        result_text=EXECUTOR_REPORT,
    )


def _queued(seams: _Seams, undone: str) -> "trd.FinishedTodoRun":
    """Return the payload of the one finish job queued, checking its key and delay."""
    pool, task, payload = seams.enqueue.await_args.args
    assert (pool, task) == (seams.pool, todo_constants.TODO_RUN_FINISH_TASK)
    assert seams.enqueue.await_args.kwargs == {
        "_job_id": f"{todo_constants.TODO_RUN_FINISH_JOB_PREFIX}{payload.run_id}:{undone}",
        "_defer_by": todo_constants.TODO_RUN_FINISH_RETRY_DELAY,
    }
    assert (payload.todo_id, payload.user_id) == (TODO_ID, USER.user_id)
    return payload


def _assert_failed_loudly(event: dict[str, Any], failure: str, cause: str) -> None:
    """Assert the event failed for this reason, with one error naming the run, todo and cause."""
    assert (event["outcome"], event["reason"]) == ("failed", failure)
    [error] = event["errors"]
    assert error["msg"].startswith(LogTag.AGENT)
    assert (error["failure"], error["todo_id"], error["cause"]) == (failure, TODO_ID, cause)
    assert error["run_id"]
