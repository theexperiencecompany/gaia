"""A tracked todo's run files the executor's report with the outbox, once, or nothing.

Regression for the 2026-09-26 Telegram message "Dispatched the only actionable
step… Task in flight; result will land on its own": the run went through comms,
which handed off to the executor and wrote that acknowledgement before any work
happened. The run now goes straight to the executor and its outcome is what the
outbox is told.

Real here: run_todo_on_executor, run_executor_background, finalize, the outcome the run is
reported with, todo delivery and the activity entry. Faked: the executor model call, Redis,
the activity store and the outbox's submit (its own tests cover what it does with a report).
"""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from arq import Retry
from langchain_core.messages import SystemMessage
from pymongo.errors import PyMongoError
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.agents.context import presence_note
from app.agents.context.assemble import AssembledContext
from app.agents.context.slots import PRESENCE_NOTE_MARKER, has_marker
from app.agents.context.tiers import AgentTier
from app.agents.core.background import (
    executor_runner as er,
    run_cards as rc,
    session as sess,
    todo_run,
    todo_run_delivery as trd,
)
from app.agents.core.background.executor_queue import build_lock_value
from app.agents.core.background.executor_runner import _ExecutorResult
from app.agents.core.background.run_report import RunOutcome
from app.agents.core.background.session import RunKind, TodoRun, get_session
from app.agents.core.background.todo_run import (
    TODO_EXECUTOR_TASK_NAME,
    TodoRunFailedError,
    TodoRunRequest,
    run_todo_on_executor,
)
from app.agents.core.outcome_review import OutcomeReview
from app.agents.core.subagents import subagent_runner
from app.constants import todos as todo_constants
from app.constants.agents import OutcomeState
from app.constants.log_tags import LogTag
from app.constants.todos import TodoActivityEvent, TodoWakeKind
from app.models.chat_models import ConversationSource
from app.models.message_models import TodoRunWake
from app.models.task_report_models import FinishTaskArgs, TaskReport
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType
from app.services import todo_activity
from app.services.delivery.presence import record_turn_presence
from app.services.outbox.models import Initiative, ProducerKind, RunReport
from app.services.outbox.router import InApp
from app.services.outbox.transport import ws_speech
from app.utils.background_tasks import spawn_background_task
from app.workers.tasks import tracked_todo_tasks
from tests.helpers import WideEventRecorder, captured_wide_event

# A run says it lives in Redis while it runs: give it a per-test Redis, never the ambient one.
pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("fake_redis")]

USER = AuthenticatedUser(user_id="507f1f77bcf86cd799439011", email="d@gaia.local")
TODO_ID = "6ab51f1ba7a1fcf0f00ab49a"
EXECUTOR_REPORT = "Checked staging. The deploy failed on migration 42; needs a rollback call."


#: A finished run whose report the review confirms: the executor result carries a context to review.
_DONE_REVIEW = OutcomeReview(
    OutcomeState.DONE, None, FinishTaskArgs(result=EXECUTOR_REPORT, outcome=OutcomeState.DONE)
)
_DONE = _ExecutorResult(EXECUTOR_REPORT, "final", ctx=MagicMock())


def _todo(*, notify_on_run: bool = True, **fields: Any) -> TodoDocument:
    return TodoDocument(
        id=TODO_ID,
        user_id=USER.user_id,
        title="Watch the staging deploy",
        labels=["gaia-tracked"],
        notify_on_run=notify_on_run,
        canvas_content="## Standing rules\n- Tell me when a deploy fails.\n\n## Current State\n- green\n",
        **fields,
    )


@dataclass
class _Seams:
    submit: AsyncMock
    record_report: AsyncMock
    activity: AsyncMock
    save_to_conversation: AsyncMock
    execute: AsyncMock
    lock: AsyncMock
    spawn: MagicMock
    repo: MagicMock
    enqueue: AsyncMock
    pool: MagicMock


@contextmanager
def _seams(
    *,
    todo: TodoDocument,
    executor: _ExecutorResult | None = None,
) -> Iterator[_Seams]:
    seams = _Seams(
        submit=AsyncMock(),
        record_report=AsyncMock(),
        activity=AsyncMock(return_value=True),
        save_to_conversation=AsyncMock(),
        execute=AsyncMock(return_value=executor or _DONE),
        lock=AsyncMock(return_value=True),
        spawn=MagicMock(side_effect=spawn_background_task),
        repo=MagicMock(get_by_id=AsyncMock(return_value=todo)),
        enqueue=AsyncMock(),
        pool=MagicMock(),
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
        patch.object(rc, "update_messages", seams.save_to_conversation),
        patch.object(trd, "submit", seams.submit),
        patch.object(trd, "record_executor_report", seams.record_report),
        patch.object(er, "_review_outcome", AsyncMock(return_value=_DONE_REVIEW)),
        patch.object(trd, "todo_repository", seams.repo),
        patch.object(todo_activity, "append_activity", seams.activity),
        patch.object(trd, "enqueue_worker_job", seams.enqueue),
        patch.object(
            trd, "RedisPoolManager", MagicMock(get_pool=AsyncMock(return_value=seams.pool))
        ),
    ):
        yield seams
    sess._sessions.clear()


def _no_backoff() -> AbstractContextManager[AsyncMock]:
    """Skip the Mongo retry's backoff sleeps; the attempts themselves still run."""
    # By name: the policy's module is newer than the regression lane's base.
    return patch("app.db.mongodb.retry.TRANSIENT_MONGO_RETRY.sleep", AsyncMock())


def _request(*, runs_once: bool = True) -> TodoRunRequest:
    return TodoRunRequest(
        user=USER,
        todo_run=TodoRun(
            todo_id=TODO_ID, trigger_type=TriggerType.SCHEDULED_TODO, runs_once=runs_once
        ),
        todo_title="Watch the staging deploy",
        task="Execute the following scheduled task: Watch the staging deploy",
        conversation_id="run-conv-1",
        fresh_thread=False,
        wake=TodoRunWake(
            kind=TodoWakeKind.SCHEDULE,
            trigger_names=[],
            approval_summary=None,
        ),
    )


def _activity(seams: _Seams) -> str:
    """Return the run's finish entry on the todo's timeline, after its run id."""
    todo_id, user_id, entry = seams.activity.await_args.args
    assert (todo_id, user_id) == (TODO_ID, USER.user_id)
    return entry.split(f"[{TodoActivityEvent.RUN_FINISHED.value}] run ", 1)[1].split(": ", 1)[1]


class TestTheExecutorsResultIsWhatReachesTheUser:
    async def test_the_run_files_its_report_with_the_outbox_under_the_todos_rules(self) -> None:
        with _seams(todo=_todo()) as seams:
            await run_todo_on_executor(_request())

        seams.submit.assert_awaited_once()
        report: RunReport = seams.submit.await_args.args[0]
        run = seams.execute.await_args.args[2]
        assert report.producer is ProducerKind.TODO
        assert report.report_id == f"todo:{TODO_ID}:{run.stream_id}"
        assert (report.recipient, report.subject.label) == (
            USER.user_id,
            "Watch the staging deploy",
        )
        # The run's chat keeps its own record; the message is told where the user is, not there.
        assert report.subject.owner_conversation_id is None
        assert report.subject.series == f"todo:{TODO_ID}"
        assert (report.report.outcome, report.result) == (OutcomeState.DONE, EXECUTOR_REPORT)
        # No schedule and no watch: it exists to answer what the user asked.
        assert report.initiative is Initiative.ASKED
        assert report.guidance is not None
        assert (report.guidance.standing_rules, report.guidance.runs_once) == (
            "- Tell me when a deploy fails.",
            True,
        )
        seams.record_report.assert_awaited_once_with("run-conv-1", EXECUTOR_REPORT, "final")
        seams.repo.get_by_id.assert_awaited_once_with(TODO_ID)

    async def test_the_executors_own_report_is_kept_in_the_todos_chat(self) -> None:
        """Regression: the run's conversation was a throwaway, so nothing the run did was left to open."""
        broadcast = AsyncMock()
        with (
            _seams(todo=_todo()) as seams,
            patch.object(ws_speech, "websocket_manager", MagicMock(broadcast_to_user=broadcast)),
        ):
            await run_todo_on_executor(_request())

        (saved,) = seams.save_to_conversation.await_args.args
        run = seams.execute.await_args.args[2]
        assert saved.conversation_id == "run-conv-1"
        (message,) = saved.messages
        # The report itself, not comms' retelling: the chat is the record of the run.
        assert (message.type, message.response, message.error) == ("bot", EXECUTOR_REPORT, None)
        # Under the placeholder id the live stream rendered into, so it replaces it.
        assert message.message_id == run.task_id
        # Every run adds one, so the chat is capped at its newest messages.
        assert seams.save_to_conversation.await_args.kwargs["max_messages"] == (
            todo_constants.TODO_CONVERSATION_MAX_MESSAGES
        )
        user_id, event = broadcast.await_args.args
        assert user_id == USER.user_id
        assert event["type"] == "outbox.message"
        assert event["kind"] == "conversation_message"
        assert event["conversation_id"] == "run-conv-1"
        assert event["message"]["message_id"] == run.task_id
        assert event["message"]["task_id"] == run.task_id
        assert event["message"]["response"] == EXECUTOR_REPORT

    async def test_a_failed_run_is_kept_in_the_todos_chat_as_its_error(self) -> None:
        with (
            _seams(
                todo=_todo(), executor=_ExecutorResult("The calendar API was down.", "error")
            ) as seams,
            patch.object(ws_speech, "websocket_manager", MagicMock(broadcast_to_user=AsyncMock())),
            pytest.raises(TodoRunFailedError),
        ):
            await run_todo_on_executor(_request())

        (message,) = seams.save_to_conversation.await_args.args[0].messages
        assert (message.response, message.error) == ("", "The calendar API was down.")
        seams.submit.assert_not_awaited()

    async def test_a_report_the_chat_cannot_keep_still_reaches_the_outbox(self) -> None:
        """The record and the message are independent: losing one must not lose the other."""
        with _seams(todo=_todo()) as seams:
            seams.save_to_conversation.side_effect = RuntimeError("mongo is down")
            await run_todo_on_executor(_request())

        seams.submit.assert_awaited_once()

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
        assert run.todo_run == TodoRun(
            todo_id=TODO_ID, trigger_type=TriggerType.SCHEDULED_TODO, runs_once=True
        )
        assert (run.kind, run.conversation_id, run.user_message_id) == (
            RunKind.LIVE,
            "run-conv-1",
            None,
        )
        assert run.stream_id and run.task_id and run.t_dispatch_perf is not None

    async def test_the_executor_opens_with_the_background_presence_note(self) -> None:
        """The run's own configurable (background, no chat source) seeds the executor thread with it."""
        await record_turn_presence(USER.user_id, ConversationSource.TELEGRAM)
        with _seams(todo=_todo()) as seams:
            await run_todo_on_executor(_request())
        task, configurable, _run, _resume = seams.execute.await_args.args

        with (
            patch.object(
                subagent_runner,
                "assemble_context",
                AsyncMock(
                    return_value=AssembledContext(
                        stable=SystemMessage(content="ctx"), volatile=None
                    )
                ),
            ),
            patch.object(
                presence_note,
                "resolve_proactive_target",
                AsyncMock(return_value=InApp(reason="no_chat_app")),
            ),
        ):
            messages = await subagent_runner.build_initial_messages(
                system_message=SystemMessage(content="sys"),
                agent_name="executor_agent",
                task=task,
                seed=subagent_runner.ThreadSeed(
                    tier=AgentTier.EXECUTOR, configurable=configurable, user_id=USER.user_id
                ),
            )

        (note,) = [m for m in messages if has_marker(m, PRESENCE_NOTE_MARKER)]
        assert str(note.content).startswith(
            "[User presence: this is a background run, so the user sees only what it sends them. "
            "Last seen: Telegram at "
        )
        assert messages[messages.index(note) + 1].content == task

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

    async def test_the_outcome_is_recorded_on_the_todos_timeline(self) -> None:
        with _seams(todo=_todo()) as seams:
            await run_todo_on_executor(_request())

        assert _activity(seams).startswith(
            "reported to the outbox: done (summary='Checked staging."
        )


class TestNothingIsReportedWhenNothingShouldBe:
    async def test_delivery_turned_off_during_the_run_is_carried_on_the_report(self) -> None:
        """notify_on_run is read at the end: the prod run turned it off mid-run and still pinged."""
        with _seams(todo=_todo(notify_on_run=False)) as seams:
            await run_todo_on_executor(_request())

        report: RunReport = seams.submit.await_args.args[0]
        assert report.delivery_policy.notify is False

    async def test_a_todo_that_repeats_reports_on_its_own(self) -> None:
        with _seams(todo=_todo(recurrence="FREQ=HOURLY")) as seams:
            await run_todo_on_executor(_request(runs_once=False))

        report: RunReport = seams.submit.await_args.args[0]
        assert report.initiative is Initiative.SELF_INITIATED
        assert report.guidance is not None
        assert report.guidance.runs_once is False

    async def test_an_executor_error_raises_for_the_retry_ladder_and_reports_nothing(self) -> None:
        with (
            _seams(todo=_todo(), executor=_ExecutorResult("tool exploded", "error")) as seams,
            pytest.raises(TodoRunFailedError, match="tool exploded"),
        ):
            await run_todo_on_executor(_request())

        seams.submit.assert_not_awaited()
        seams.activity.assert_not_awaited()
        # The chat still shows it, so the chat's next turn must know it.
        seams.record_report.assert_awaited_once_with("run-conv-1", "tool exploded", "error")


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
        assert "reported to the outbox: done (summary=" in entry
        seams.submit.assert_awaited_once()
        seams.enqueue.assert_not_awaited()

    @pytest.mark.regression
    async def test_a_todo_read_that_fails_once_is_retried_and_the_result_still_delivered(
        self,
    ) -> None:
        """Regression: a failed read of the todo dropped the finished run's message and entry."""
        with _seams(todo=_todo()) as seams, _no_backoff():
            seams.repo.get_by_id.side_effect = [PyMongoError("primary stepped down"), _todo()]
            await run_todo_on_executor(_request())

        seams.submit.assert_awaited_once()
        assert _activity(seams).startswith("reported to the outbox: done (summary=")

    async def test_a_read_that_keeps_failing_is_delivered_by_the_runs_job(self) -> None:
        with _seams(todo=_todo()) as seams, _no_backoff():
            seams.repo.get_by_id.side_effect = PyMongoError("primary stepped down")
            await run_todo_on_executor(_request())
            seams.submit.assert_not_awaited()
            undone = _queued(seams, "todo_run_result_not_delivered")

            seams.repo.get_by_id.side_effect = None
            await tracked_todo_tasks.finish_tracked_todo_run({"job_try": 2}, undone)

        seams.submit.assert_awaited_once()
        assert _activity(seams).startswith("reported to the outbox: done (summary=")
        assert seams.execute.await_count == 1

    async def test_a_report_the_queue_refuses_is_filed_by_the_runs_job(self) -> None:
        with _seams(todo=_todo()) as seams, _no_backoff():
            seams.submit.side_effect = RedisConnectionError("redis down")
            await run_todo_on_executor(_request())
            undone = _queued(seams, "todo_run_result_not_delivered")

            seams.submit.side_effect = None
            await tracked_todo_tasks.finish_tracked_todo_run({"job_try": 2}, undone)

        assert seams.submit.await_count == 2
        assert seams.execute.await_count == 1

    async def test_an_entry_that_keeps_failing_is_written_by_its_job_without_a_second_report(
        self,
    ) -> None:
        with _seams(todo=_todo()) as seams, _no_backoff():
            seams.activity.side_effect = PyMongoError("primary stepped down")
            await run_todo_on_executor(_request())
            undone = _queued(seams, "todo_run_result_not_recorded")

            seams.activity.side_effect = None
            await tracked_todo_tasks.finish_tracked_todo_run({"job_try": 1}, undone)

        seams.submit.assert_awaited_once()
        assert _activity(seams).startswith("reported to the outbox: done (summary=")

    async def test_a_job_that_files_but_cannot_record_hands_the_entry_on(self) -> None:
        """A replay of the filing job would file again; the entry gets a job of its own."""
        with _seams(todo=_todo()) as seams, _no_backoff():
            seams.activity.side_effect = PyMongoError("primary stepped down")
            await tracked_todo_tasks.finish_tracked_todo_run({"job_try": 1}, _undelivered())

        seams.submit.assert_awaited_once()
        undone = _queued(seams, "todo_run_result_not_recorded")
        assert "reported to the outbox: done (summary=" in (undone.finish_entry or "")

    async def test_a_job_for_a_run_already_finished_reports_nothing(self) -> None:
        marker = f"[{TodoActivityEvent.RUN_FINISHED.value}] run run-1:"
        todo = _todo().model_copy(update={"activity_content": f"- t {marker} result sent"})
        with _seams(todo=todo) as seams:
            await tracked_todo_tasks.finish_tracked_todo_run({"job_try": 1}, _undelivered())

        seams.submit.assert_not_awaited()
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
        seams.submit.assert_not_awaited()
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
        assert store_failure["msg"].startswith(LogTag.AGENT)
        assert (
            store_failure["todo_id"],
            store_failure["run_id"],
            store_failure["undone"],
            store_failure["error"],
            store_failure["error_type"],
        ) == (
            TODO_ID,
            event["stream_id"],
            "todo_run_result_not_delivered",
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
        outcome=RunOutcome(report=TaskReport(outcome=OutcomeState.DONE), result=EXECUTOR_REPORT),
        runs_once=True,
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
