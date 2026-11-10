"""The executor run trace against real Mongo + Redis: what a run leaves behind, and who can read it.

Not reached: the tool registry (a stub answers is_tool_destructive, which the real registry
holds per tool) and the todo canvas's embedding and sync side effects.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest
from redis.asyncio import Redis

from app.agents.core.background.executor_queue import build_lock_value, keep_alive
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.constants.run_trace import (
    CALL_PAYLOAD_MAX_CHARS,
    CALL_PAYLOADS_COLLECTION,
    CALL_SUMMARY_MAX_CHARS,
    RUN_ABANDONED_AFTER_SECONDS,
    RUN_CALLS_COLLECTION,
    RUN_TRACE_RETENTION_SECONDS,
    RUNS_COLLECTION,
)
from app.db.mongodb.indexes import create_run_trace_indexes
from app.db.repositories.run_traces import (
    call_payload_repository,
    run_call_repository,
    run_repository,
)
from app.db.repositories.todos import todo_repository
from app.models.run_trace_models import (
    CallEffect,
    CallPayloadDocument,
    CallStatus,
    RunCallDocument,
    RunDocument,
    RunState,
)
from app.models.todo_models import TodoDocument
from app.services.executor_trace.recorder import (
    RunOwner,
    TracedCall,
    begin_run,
    end_run,
    reap_abandoned_runs,
    record_call,
)

pytestmark = pytest.mark.service

TRACE_COLLECTIONS = (RUNS_COLLECTION, RUN_CALLS_COLLECTION, CALL_PAYLOADS_COLLECTION)
CONVERSATION = "c0ffee00-0000-4000-8000-000000000001"


class _Registry:
    """The tool registry's one answer the trace reads: a tool's HIL destructiveness."""

    def __init__(self, destructive: dict[str, bool]) -> None:
        self._destructive = destructive

    def is_tool_destructive(self, tool_name: str) -> bool | None:
        return self._destructive.get(tool_name)


@pytest.fixture(autouse=True)
async def _clean_traces(mongo_db: AsyncIOMotorDatabase) -> AsyncIterator[None]:
    for name in TRACE_COLLECTIONS:
        await mongo_db[name].delete_many({})
    yield
    for name in TRACE_COLLECTIONS:
        await mongo_db[name].delete_many({})


@pytest.fixture(autouse=True)
def _registry() -> Iterator[None]:
    registry = _Registry({"gmail_send_email": True, "gmail_search": False})
    with patch(
        "app.services.executor_trace.recorder.get_tool_registry",
        new_callable=AsyncMock,
        return_value=registry,
    ):
        yield


@pytest.fixture(autouse=True)
def _offline_canvas() -> Iterator[None]:
    with (
        patch("app.services.todo_canvas_storage.schedule_gaia_tasks_sync", MagicMock()),
        patch("app.services.todo_canvas_storage._schedule_reindex", MagicMock()),
    ):
        yield


def _owner(user_id: str, *, todo_id: str | None = None, run_id: str | None = None) -> RunOwner:
    return RunOwner(
        user_id=user_id,
        conversation_id=CONVERSATION,
        run_id=run_id or str(uuid4()),
        todo_id=todo_id,
    )


def _call(
    tool: str = "gmail_search",
    *,
    args: dict[str, object] | None = None,
    output: str = "3 threads",
    failed: bool = False,
    at: datetime | None = None,
) -> TracedCall:
    started = at or datetime.now(UTC)
    return TracedCall(
        tool_name=tool,
        tool_call_id="toolu_1",
        args={"query": "lease"} if args is None else args,
        output_text=output,
        failed=failed,
        started_at=started,
        finished_at=started + timedelta(seconds=1),
    )


async def list_run_calls(user_id: str, run_id: str) -> list[RunCallDocument]:
    calls = await run_call_repository.list_for_user(user_id, sort=[("started_at", 1)])
    return [c for c in calls if c.run_id == run_id]


async def list_conversation_runs(user_id: str, conversation_id: str) -> list[RunDocument]:
    runs = await run_repository.list_for_user(user_id, sort=[("started_at", -1)])
    return [r for r in runs if r.conversation_id == conversation_id]


async def list_todo_runs(user_id: str, todo_id: str) -> list[RunDocument]:
    runs = await run_repository.list_for_user(user_id, sort=[("started_at", -1)])
    return [r for r in runs if r.todo_id == todo_id]


async def _payload(user_id: str, call: RunCallDocument) -> CallPayloadDocument:
    payload = await call_payload_repository.get(call.payload_ref, user_id=user_id)
    assert payload is not None
    return payload


async def _todo(user_id: str) -> str:
    todo = await todo_repository.create(TodoDocument(user_id=user_id, title="Reply to Sam"))
    return todo.id


async def _activity(user_id: str, todo_id: str) -> str:
    doc = await todo_repository.get(todo_id, user_id=user_id)
    assert doc is not None
    return doc.activity_content or ""


class TestRecordingACall:
    async def test_a_call_keeps_its_effect_status_and_summary_and_not_its_payload(
        self, user_id: str
    ) -> None:
        owner = _owner(user_id)

        await record_call(owner, _call("gmail_send_email", args={"to": "sam@example.com"}))

        (call,) = await list_run_calls(user_id, owner.run_id)
        assert (call.tool_name, call.effect, call.status) == (
            "gmail_send_email",
            CallEffect.WRITE,
            CallStatus.OK,
        )
        assert call.summary == "to=sam@example.com"
        assert not hasattr(call, "output_text")

    @pytest.mark.parametrize(
        ("tool", "effect"),
        [
            ("gmail_search", CallEffect.READ),
            ("gmail_send_email", CallEffect.WRITE),
            ("a_tool_nobody_classified", CallEffect.WRITE),
        ],
    )
    async def test_effect_comes_from_the_registry_and_unclassified_counts_as_a_write(
        self, user_id: str, tool: str, effect: CallEffect
    ) -> None:
        owner = _owner(user_id)

        await record_call(owner, _call(tool))

        (call,) = await list_run_calls(user_id, owner.run_id)
        assert call.effect is effect

    async def test_a_failed_call_is_an_error_whose_summary_names_the_failure(
        self, user_id: str
    ) -> None:
        owner = _owner(user_id)

        await record_call(owner, _call(output="Error: RuntimeError: no quota\ntrace", failed=True))

        (call,) = await list_run_calls(user_id, owner.run_id)
        assert call.status is CallStatus.ERROR
        assert call.summary.startswith("Error: RuntimeError: no quota")

    async def test_the_full_input_and_output_live_in_their_own_collection_behind_a_reference(
        self, user_id: str, mongo_db: AsyncIOMotorDatabase
    ) -> None:
        owner = _owner(user_id)
        await record_call(owner, _call(args={"query": "lease"}, output="the whole body"))
        (call,) = await list_run_calls(user_id, owner.run_id)

        detail = await _payload(user_id, call)

        assert (detail.input_json, detail.output_text, detail.truncated) == (
            '{"query": "lease"}',
            "the whole body",
            False,
        )
        stored_call = await mongo_db[RUN_CALLS_COLLECTION].find_one({"call_id": call.call_id})
        assert stored_call is not None and "the whole body" not in str(stored_call)
        assert str(stored_call["payload_ref"]) == call.payload_ref

    async def test_an_oversized_output_is_cut_at_the_bound_and_flagged(self, user_id: str) -> None:
        owner = _owner(user_id)
        await record_call(owner, _call(output="x" * (CALL_PAYLOAD_MAX_CHARS + 5)))
        (call,) = await list_run_calls(user_id, owner.run_id)

        detail = await _payload(user_id, call)

        assert len(detail.output_text) == CALL_PAYLOAD_MAX_CHARS and detail.truncated

    async def test_a_long_summary_stays_within_its_bound(self, user_id: str) -> None:
        owner = _owner(user_id)

        await record_call(owner, _call(args={"body": "word " * 200, "to": "a" * 300}))

        (call,) = await list_run_calls(user_id, owner.run_id)
        assert len(call.summary) <= CALL_SUMMARY_MAX_CHARS


class TestWhoOwnsARun:
    async def test_a_todos_run_attaches_to_the_todo_and_its_calls_become_activity_lines(
        self, user_id: str
    ) -> None:
        todo_id = await _todo(user_id)
        owner = _owner(user_id, todo_id=todo_id)
        await begin_run(owner)
        await record_call(owner, _call("gmail_search"))
        await record_call(owner, _call("gmail_send_email", args={"to": "sam@example.com"}))

        await end_run(owner, RunState.FINISHED)

        (run,) = await list_todo_runs(user_id, todo_id)
        assert (run.run_id, run.todo_id, run.state) == (owner.run_id, todo_id, RunState.FINISHED)
        lines = (await _activity(user_id, todo_id)).splitlines()
        assert len(lines) == 2
        assert "[tool_called] read gmail_search ok: query=lease" in lines[0]
        assert "[tool_called] write gmail_send_email ok: to=sam@example.com" in lines[1]

    async def test_a_comms_run_is_a_hidden_record_keyed_by_conversation_and_run_without_a_todo(
        self, user_id: str
    ) -> None:
        owner = _owner(user_id)
        await begin_run(owner)
        await record_call(owner, _call())
        await end_run(owner, RunState.FINISHED)

        (run,) = await list_conversation_runs(user_id, CONVERSATION)

        assert (run.run_id, run.conversation_id, run.todo_id) == (
            owner.run_id,
            CONVERSATION,
            None,
        )

    async def test_activity_is_logged_once_across_a_pause_and_the_resume(
        self, user_id: str
    ) -> None:
        todo_id = await _todo(user_id)
        owner = _owner(user_id, todo_id=todo_id)
        await begin_run(owner)
        await record_call(owner, _call("gmail_search"))
        await end_run(owner, RunState.PAUSED)
        await begin_run(owner)
        await record_call(owner, _call("gmail_send_email"))

        await end_run(owner, RunState.FINISHED)

        lines = (await _activity(user_id, todo_id)).splitlines()
        assert [("gmail_search" in line, "gmail_send_email" in line) for line in lines] == [
            (True, False),
            (False, True),
        ]


class TestRunStates:
    async def test_a_run_is_running_until_it_ends_and_a_resumed_run_runs_again(
        self, user_id: str
    ) -> None:
        owner = _owner(user_id)

        await begin_run(owner)
        (running,) = await list_conversation_runs(user_id, CONVERSATION)
        await end_run(owner, RunState.PAUSED)
        (paused,) = await list_conversation_runs(user_id, CONVERSATION)
        await begin_run(owner)
        (resumed,) = await list_conversation_runs(user_id, CONVERSATION)
        await end_run(owner, RunState.FAILED)
        (failed,) = await list_conversation_runs(user_id, CONVERSATION)

        assert [r.state for r in (running, paused, resumed, failed)] == [
            RunState.RUNNING,
            RunState.PAUSED,
            RunState.RUNNING,
            RunState.FAILED,
        ]
        assert (running.finished_at, paused.finished_at, resumed.finished_at) == (None,) * 3
        assert failed.finished_at is not None

    async def test_a_call_from_a_run_nobody_opened_creates_the_run_and_keeps_it_running(
        self, user_id: str
    ) -> None:
        owner = _owner(user_id)

        await record_call(owner, _call())

        (run,) = await list_conversation_runs(user_id, CONVERSATION)
        assert (run.run_id, run.state) == (owner.run_id, RunState.RUNNING)

    async def test_a_late_call_does_not_reopen_a_finished_run(self, user_id: str) -> None:
        owner = _owner(user_id)
        await begin_run(owner)
        await end_run(owner, RunState.FINISHED)

        await record_call(owner, _call())

        (run,) = await list_conversation_runs(user_id, CONVERSATION)
        assert run.state is RunState.FINISHED


class TestParentRun:
    async def test_a_subagent_run_records_the_run_that_dispatched_it_and_a_top_level_run_none(
        self, user_id: str
    ) -> None:
        parent = _owner(user_id)
        child = RunOwner(
            user_id=user_id,
            conversation_id=CONVERSATION,
            run_id=str(uuid4()),
            parent_run_id=parent.run_id,
        )
        await begin_run(parent)
        await begin_run(child)
        await record_call(child, _call())

        runs = {r.run_id: r for r in await list_conversation_runs(user_id, CONVERSATION)}

        assert runs[child.run_id].parent_run_id == parent.run_id
        assert runs[parent.run_id].parent_run_id is None


class TestTheReaper:
    async def _stale_run(
        self, user_id: str, mongo_db: AsyncIOMotorDatabase, *, todo_id: str | None = None
    ) -> RunOwner:
        owner = _owner(user_id, todo_id=todo_id)
        await begin_run(owner)
        await record_call(owner, _call())
        long_ago = datetime.now(UTC) - timedelta(seconds=RUN_ABANDONED_AFTER_SECONDS + 60)
        await mongo_db[RUNS_COLLECTION].update_one(
            {"run_id": owner.run_id}, {"$set": {"last_activity_at": long_ago}}
        )
        return owner

    async def test_a_run_left_running_past_the_timeout_is_marked_abandoned_with_its_activity(
        self, user_id: str, mongo_db: AsyncIOMotorDatabase, real_redis: Redis
    ) -> None:
        todo_id = await _todo(user_id)
        owner = await self._stale_run(user_id, mongo_db, todo_id=todo_id)

        closed = await reap_abandoned_runs()

        (run,) = await list_todo_runs(user_id, todo_id)
        assert (closed, run.state) == (1, RunState.ABANDONED)
        assert run.finished_at is not None
        assert "[tool_called] read gmail_search ok" in await _activity(user_id, todo_id)
        assert run.run_id == owner.run_id

    async def test_a_recently_active_run_is_left_running(
        self, user_id: str, real_redis: Redis
    ) -> None:
        owner = _owner(user_id)
        await begin_run(owner)
        await record_call(owner, _call())

        closed = await reap_abandoned_runs()

        (run,) = await list_conversation_runs(user_id, CONVERSATION)
        assert (closed, run.state) == (0, RunState.RUNNING)

    async def test_a_run_whose_executor_still_holds_the_busy_lock_is_left_running(
        self, user_id: str, mongo_db: AsyncIOMotorDatabase, real_redis: Redis
    ) -> None:
        owner = await self._stale_run(user_id, mongo_db)
        lock_value = build_lock_value(owner.run_id, "task-1")
        await real_redis.set(f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}", lock_value, ex=600)
        alive = await keep_alive(CONVERSATION, lock_value)
        try:
            closed = await reap_abandoned_runs()
        finally:
            alive.cancel()

        (run,) = await list_conversation_runs(user_id, CONVERSATION)
        assert (closed, run.state) == (0, RunState.RUNNING)

    async def test_a_paused_run_is_not_reaped(
        self, user_id: str, mongo_db: AsyncIOMotorDatabase, real_redis: Redis
    ) -> None:
        owner = await self._stale_run(user_id, mongo_db)
        await end_run(owner, RunState.PAUSED)
        long_ago = datetime.now(UTC) - timedelta(seconds=RUN_ABANDONED_AFTER_SECONDS + 60)
        await mongo_db[RUNS_COLLECTION].update_one(
            {"run_id": owner.run_id}, {"$set": {"last_activity_at": long_ago}}
        )

        closed = await reap_abandoned_runs()

        (run,) = await list_conversation_runs(user_id, CONVERSATION)
        assert (closed, run.state) == (0, RunState.PAUSED)


class TestRetention:
    async def test_every_trace_collection_expires_on_created_at_after_the_retention_window(
        self, mongo_db: AsyncIOMotorDatabase
    ) -> None:
        with patch("app.db.mongodb.indexes.get_async_collection", lambda name: mongo_db[name]):
            await create_run_trace_indexes()

        for name in TRACE_COLLECTIONS:
            info = await mongo_db[name].index_information()
            ttl = [
                index
                for index in info.values()
                if index["key"] == [("created_at", 1)] and "expireAfterSeconds" in index
            ]
            assert [index["expireAfterSeconds"] for index in ttl] == [
                RUN_TRACE_RETENTION_SECONDS
            ], name
