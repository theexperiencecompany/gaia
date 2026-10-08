"""Unit tests for deliver_to_executor's handoff to the background executor.

One invariant: work appended while a run is finalizing must still get a run.
The old run's carry reads the inbox exactly once, so an entry that lands after
that read and after the lock release would sit unseen until unrelated future
activity. The append is therefore followed by a recheck that starts a carry
run when the lock is free.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from app.agents.core.background import (
    executor_channel as ec,
    executor_queue as eq,
    executor_runner as er,
)
from app.agents.core.background.executor_channel import ExecutorInbox
from app.agents.core.background.executor_queue import (
    build_lock_value,
    get_lock_holder,
    release_lock_if_owned,
)
from app.agents.core.background.session import ExecutorRun, RunKind
from app.constants.agents import AgentTag
from app.constants.cache import (
    EXECUTOR_ALIVE_PREFIX,
    EXECUTOR_BUSY_PREFIX,
    EXECUTOR_BUSY_TTL,
    EXECUTOR_DEAD_HOLDER_MIN_AGE_SECONDS,
)
from app.constants.executor import EXECUTOR_CARRY_TASK
from app.constants.log_tags import LogTag
from app.models.agent_models import InboxEntry
from app.models.user_models import AuthenticatedUser
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

CONVERSATION = "conv-1"
TASK = "summarize the thread"


def _seams(*, busy: list[bool], started: bool):
    """Patch deliver_to_executor's seams: the free-or-freed lock check, run start, inbox.

    busy answers successive checks of THIS conversation; any other id reads free.
    """
    answers = iter(busy)

    async def _free_after_reclaim(conversation_id: str) -> bool:
        # Each check reclaims a dead holder first: free means no live run holds it.
        return not next(answers) if conversation_id == CONVERSATION else True

    stack = patch.object(er, "reclaim_dead_lock", _free_after_reclaim)
    start = patch.object(er, "_start_executor_run", new_callable=AsyncMock, return_value=started)
    append = patch.object(er.ExecutorInbox, "append", new_callable=AsyncMock)
    return stack, start, append


class TestMidFinalizeWorkGetsARun:
    async def test_an_append_after_the_old_runs_carry_starts_a_carry_run(self) -> None:
        """Busy at entry (old run finalizing), free after the append (released, carry missed it)."""
        busy, start, append = _seams(busy=[True, False], started=True)
        with busy, start as start_mock, append as append_mock:
            await er.deliver_to_executor(CONVERSATION, AuthenticatedUser(user_id="u1"), TASK)

        append_mock.assert_awaited_once()  # the work is never dropped from the inbox
        start_mock.assert_awaited_once()  # ...nor left without a run to drain it
        assert start_mock.await_args.args[2] == EXECUTOR_CARRY_TASK

    async def test_a_live_run_absorbs_the_append_with_no_extra_start(self) -> None:
        busy, start, append = _seams(busy=[True, True], started=False)
        with busy, start as start_mock, append as append_mock:
            await er.deliver_to_executor(CONVERSATION, AuthenticatedUser(user_id="u1"), TASK)

        append_mock.assert_awaited_once()
        start_mock.assert_not_awaited()

    async def test_an_idle_conversation_starts_a_run_for_the_task_itself(self) -> None:
        busy, start, append = _seams(busy=[False], started=True)
        with busy, start as start_mock, append as append_mock:
            await er.deliver_to_executor(CONVERSATION, AuthenticatedUser(user_id="u1"), TASK)

        start_mock.assert_awaited_once()
        assert start_mock.await_args.args[2] == TASK
        append_mock.assert_not_awaited()


class TestTaggedWorkTravelsThroughTheInbox:
    async def test_an_idle_conversation_gets_the_entry_framed_and_a_carry_run(self) -> None:
        # A subagent result must reach the model framed as a subagent result, so it is
        # never the run's bare task, even when the conversation is idle.
        busy, start, append = _seams(busy=[False], started=True)
        with busy, start as start_mock, append as append_mock:
            await er.deliver_to_executor(
                CONVERSATION, AuthenticatedUser(user_id="u1"), TASK, tag=AgentTag.SUBAGENT_RESULT
            )

        append_mock.assert_awaited_once()
        assert append_mock.await_args.args[1:] == (TASK, AgentTag.SUBAGENT_RESULT)
        start_mock.assert_awaited_once()
        assert start_mock.await_args.args[2] == EXECUTOR_CARRY_TASK


class _FakeRedisClient:
    """Enough of the raw Redis surface for the busy lock and the inbox list.

    set does its NX check and its write with no await between them, the same
    atomicity single-threaded Redis gives the claim.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(
        self, key: str, value: str, ex: int | None = None, nx: bool = False
    ) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def exists(self, key: str) -> int:
        return int(key in self.store)

    async def ttl(self, key: str) -> int:
        # Every lock here was just taken: too young to be judged dead.
        return EXECUTOR_BUSY_TTL

    async def rpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    async def expire(self, key: str, ttl: int) -> bool:
        return key in self.lists or key in self.store

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        values = self.lists.get(key, [])
        return values[start:] if end == -1 else values[start : end + 1]

    async def lrem(self, key: str, count: int, value: str) -> int:
        values = self.lists.get(key, [])
        if value not in values:
            return 0
        values.remove(value)
        return 1


class _FakeRedisCache:
    def __init__(self) -> None:
        self.client = _FakeRedisClient()

    async def delete(self, key: str) -> None:
        await self.client.delete(key)


class TestTheRealLockAndInbox:
    """The same invariant, driven through the real busy lock and the real inbox.

    The class above patches the seams that decide, so it pins the branch table
    and nothing else. This one reproduces the interleaving itself: the old run's
    whole finalize tail — its ownership-checked release and its one-time carry
    read — lands between the busy check and the append.
    """

    async def test_an_entry_landing_between_the_release_and_the_carry_gets_a_run(self) -> None:
        cache = _FakeRedisCache()
        cache.client.store[f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}"] = build_lock_value(
            "stream-a", "task-a"
        )
        old_run = ExecutorRun(
            stream_id="stream-a",
            conversation_id=CONVERSATION,
            user=AuthenticatedUser(user_id="u1"),
            kind=RunKind.QUEUED,
            task_id="task-a",
            user_message_id=None,
        )
        real_append = ExecutorInbox.append

        async def finalize_the_old_run_then_append(
            inbox: ExecutorInbox, entry_id: str, text: str, tag: AgentTag | None = None
        ) -> InboxEntry:
            await release_lock_if_owned(CONVERSATION, "stream-a", "task-a")
            await er._carry_pending_into_new_run(old_run, None)
            return await real_append(inbox, entry_id, text, tag)

        with (
            patch.object(eq, "redis_cache", cache),
            patch.object(ec, "redis_cache", cache),
            patch.object(eq, "StreamManager", AsyncMock()),
            patch.object(eq, "websocket_manager", AsyncMock()),
            patch.object(er, "_spawn_detached_run") as spawn,
            patch.object(ExecutorInbox, "append", finalize_the_old_run_then_append),
        ):
            await er.deliver_to_executor(
                CONVERSATION, AuthenticatedUser(user_id="u1"), TASK, workflow_execution_id="exec-1"
            )
            pending = await ExecutorInbox(CONVERSATION).read()

        spawn.assert_called_once()
        assert spawn.call_args.args[0].task == EXECUTOR_CARRY_TASK
        assert spawn.call_args.args[0].run.workflow_execution_id == "exec-1"
        # Left in the inbox on purpose: the new run's drain hook injects it and
        # retires it only once the thread holds it.
        assert [entry.text for entry in pending] == [TASK]


USER = AuthenticatedUser(user_id="u1", email="u1@x.com", name="Uno", timezone="Asia/Kolkata")
OTHER_RUN_LOCK = build_lock_value("other-stream", "task-9")
#: A lock taken long enough ago that its holder has had time to start renewing.
_OLD_LOCK_SECONDS = EXECUTOR_BUSY_TTL - EXECUTOR_DEAD_HOLDER_MIN_AGE_SECONDS


@contextmanager
def _real_lifecycle() -> Iterator[SimpleNamespace]:
    """Run the real busy lock and inbox over fakeredis, capturing only the spawned run."""
    with (
        patch.object(eq, "StreamManager", AsyncMock()),
        patch.object(eq, "websocket_manager", AsyncMock()),
        patch.object(er, "_spawn_detached_run") as spawn,
    ):
        yield SimpleNamespace(spawn=spawn)


def _finished_run(**overrides: Any) -> ExecutorRun:
    fields: dict[str, Any] = {
        "stream_id": "stream-a",
        "conversation_id": CONVERSATION,
        "user": USER,
        "kind": RunKind.QUEUED,
        "task_id": "task-a",
        "user_message_id": None,
    }
    return ExecutorRun(**{**fields, **overrides})


class TestTheRunAnIdleConversationGets:
    """The run deliver_to_executor starts is built from the user alone and owns the lock it took."""

    async def test_it_carries_the_task_and_nothing_is_left_in_the_inbox(self, fake_redis) -> None:
        with _real_lifecycle() as h:
            await er.deliver_to_executor(CONVERSATION, USER, TASK, workflow_execution_id="exec-1")

        (prepared, conversation_id), _ = h.spawn.call_args
        assert (prepared.task, conversation_id) == (TASK, CONVERSATION)
        assert await ExecutorInbox(CONVERSATION).read() == []
        run = prepared.run
        assert (run.conversation_id, run.workflow_execution_id) == (CONVERSATION, "exec-1")
        assert UUID(run.task_id)
        assert await get_lock_holder(CONVERSATION) == build_lock_value(run.stream_id, run.task_id)

    async def test_it_acts_as_the_user_with_a_fresh_interactive_configurable(
        self, fake_redis
    ) -> None:
        with _real_lifecycle() as h:
            await er.deliver_to_executor(CONVERSATION, USER, TASK)

        configurable = h.spawn.call_args.args[0].configurable
        assert {k: configurable[k] for k in ("user_id", "email", "user_name")} == {
            "user_id": "u1",
            "email": "u1@x.com",
            "user_name": "Uno",
        }
        assert configurable["user_timezone"] == "Asia/Kolkata"
        assert configurable["thread_id"] == CONVERSATION
        assert configurable["execution_mode"] == "interactive"

    async def test_a_user_with_no_email_or_name_gets_empty_ones(self, fake_redis) -> None:
        with _real_lifecycle() as h:
            await er.deliver_to_executor(CONVERSATION, AuthenticatedUser(user_id="u1"), TASK)

        configurable = h.spawn.call_args.args[0].configurable
        assert (configurable["email"], configurable["user_name"]) == ("", "")

    async def test_a_conversation_claimed_after_the_busy_check_keeps_the_work_queued(
        self, fake_redis
    ) -> None:
        """The busy read is only a fast path: the claim decides, and a lost claim still queues the work."""
        await fake_redis.set(f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}", OTHER_RUN_LOCK)

        with (
            _real_lifecycle() as h,
            patch.object(er, "reclaim_dead_lock", AsyncMock(return_value=True)),
        ):
            await er.deliver_to_executor(CONVERSATION, USER, TASK)

        h.spawn.assert_not_called()
        assert [e.text for e in await ExecutorInbox(CONVERSATION).read()] == [TASK]
        assert await get_lock_holder(CONVERSATION) == OTHER_RUN_LOCK

    async def test_work_for_a_busy_run_is_queued_under_its_own_id(self, fake_redis) -> None:
        await fake_redis.set(f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}", OTHER_RUN_LOCK)

        with _real_lifecycle() as h:
            await er.deliver_to_executor(CONVERSATION, USER, "first")
            await er.deliver_to_executor(CONVERSATION, USER, "second")

        h.spawn.assert_not_called()
        entries = await ExecutorInbox(CONVERSATION).read()
        assert [e.text for e in entries] == ["first", "second"]
        assert len({UUID(e.id) for e in entries}) == 2

    async def test_a_dead_holders_lock_is_reclaimed_and_the_task_gets_its_own_run(
        self, fake_redis
    ) -> None:
        """A run that died with its process stopped renewing: its lock must not hold the work back."""
        await fake_redis.set(
            f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}", OTHER_RUN_LOCK, ex=_OLD_LOCK_SECONDS
        )

        with _real_lifecycle() as h:
            await er.deliver_to_executor(CONVERSATION, USER, TASK)

        assert h.spawn.call_args.args[0].task == TASK
        assert await ExecutorInbox(CONVERSATION).read() == []

    async def test_a_holder_that_renews_keeps_the_conversation(self, fake_redis) -> None:
        """A live run, a parked one or a workflow's reservation: each renews, and keeps its lock."""
        await fake_redis.set(
            f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}", OTHER_RUN_LOCK, ex=_OLD_LOCK_SECONDS
        )
        await fake_redis.set(f"{EXECUTOR_ALIVE_PREFIX}{CONVERSATION}:{OTHER_RUN_LOCK}", "1")

        with _real_lifecycle() as h:
            await er.deliver_to_executor(CONVERSATION, USER, TASK)

        h.spawn.assert_not_called()
        assert [e.text for e in await ExecutorInbox(CONVERSATION).read()] == [TASK]
        assert await get_lock_holder(CONVERSATION) == OTHER_RUN_LOCK


class TestCarryingPendingWork:
    """A finished run's leftover inbox work gets a fresh run of its own — never a stolen lock."""

    async def test_the_carry_run_continues_the_finished_runs_conversation_and_workflow(
        self, fake_redis
    ) -> None:
        await ExecutorInbox(CONVERSATION).append("e1", "book the flight")

        with _real_lifecycle() as h:
            await er._carry_pending_into_new_run(
                _finished_run(workflow_execution_id="exec-7"), None
            )

        prepared = h.spawn.call_args.args[0]
        assert prepared.task == EXECUTOR_CARRY_TASK
        assert prepared.run.conversation_id == CONVERSATION
        assert prepared.run.workflow_execution_id == "exec-7"
        assert prepared.configurable["user_id"] == "u1"

    async def test_a_carry_never_takes_a_lock_another_run_holds(self, fake_redis) -> None:
        await fake_redis.set(f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}", OTHER_RUN_LOCK)
        await ExecutorInbox(CONVERSATION).append("e1", "book the flight")

        with _real_lifecycle() as h:
            await er._carry_pending_into_new_run(_finished_run(), None)

        h.spawn.assert_not_called()
        assert await get_lock_holder(CONVERSATION) == OTHER_RUN_LOCK
        assert [e.id for e in await ExecutorInbox(CONVERSATION).read()] == ["e1"]

    async def test_a_failed_carry_is_recorded_and_never_raises(self, fake_redis) -> None:
        with (
            patch.object(ExecutorInbox, "read", AsyncMock(side_effect=ConnectionError("down"))),
        ):
            async with captured_wide_event() as event:
                await er._carry_pending_into_new_run(_finished_run(), None)

        (error,) = event["errors"]
        assert error["msg"] == f"{LogTag.AGENT} Could not carry pending work into a new run"
        assert (error["conversation_id"], error["error_type"]) == (CONVERSATION, "ConnectionError")
