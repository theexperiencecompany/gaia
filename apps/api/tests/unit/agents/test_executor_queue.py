"""Unit tests for executor queue mechanics (executor_queue.py).

Pins the lock-handoff contract (pop overwrites the busy lock BEFORE returning,
so call_executor can never sneak in through a delete→re-set gap), the queued
session registration, and the queue-item serialization rules.
"""

import json
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.background import executor_queue as eq, session as sess
from app.agents.core.background.executor_queue import (
    LockState,
    build_lock_value,
    build_run_item,
    enqueue_task,
    get_lock_state,
    parse_lock_value,
    pop_next_queued_run,
    prepare_run_from_item,
    reclaim_stranded_task,
    release_lock_if_owned,
    safe_configurable,
)
from app.agents.core.background.session import RunKind, get_session
from app.constants.cache import EXECUTOR_BUSY_TTL, EXECUTOR_QUEUE_TTL
from app.models.agent_models import AgentConfigurable


@pytest.fixture(autouse=True)
def _clean_registry():
    sess._sessions.clear()
    yield
    sess._sessions.clear()


def _queue_item(**overrides) -> str:
    item = {
        "task": "summarize my inbox",
        "task_id": "task-7",
        "configurable": {
            "user_id": "u1",
            "email": "u1@x.com",
            "user_name": "Uno",
            "stream_id": "old-stream",
        },
        "user_time_str": "2026-06-13T10:00:00",
        "conversation_id": "conv-1",
        "user_message_id": "msg-1",
    }
    item.update(overrides)
    return json.dumps(item)


class TestLockValue:
    def test_roundtrip(self) -> None:
        value = build_lock_value("stream-1", "task-1")
        assert parse_lock_value(value) == ("stream-1", "task-1")

    def test_missing_stream_id_builds_parseable_value(self) -> None:
        assert parse_lock_value(build_lock_value(None, "task-1")) == ("", "task-1")

    def test_parse_without_separator_returns_value_as_stream(self) -> None:
        assert parse_lock_value("legacy") == ("legacy", "")


class TestPopNextQueuedRun:
    async def test_empty_queue_returns_none(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.lpop = AsyncMock(return_value=None)
            assert await pop_next_queued_run("conv-1") is None

    async def test_unparseable_item_returns_none_without_taking_lock(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.lpop = AsyncMock(return_value="{not json")
            redis.client.set = AsyncMock()
            assert await pop_next_queued_run("conv-1") is None
            redis.client.set.assert_not_awaited()

    async def test_valid_item_prepares_run_and_overwrites_lock(self) -> None:
        with (
            patch.object(eq, "redis_cache") as redis,
            patch.object(eq, "StreamManager") as sm,
            patch.object(eq, "websocket_manager") as ws,
        ):
            redis.client.lpop = AsyncMock(return_value=_queue_item())
            redis.client.set = AsyncMock()
            sm.start_stream = AsyncMock()
            ws.broadcast_to_user = AsyncMock()

            prepared = await pop_next_queued_run("conv-1")

        assert prepared is not None
        run = prepared.run

        # Run identity: QUEUED kind assigned at the pop site (never parsed
        # from the stream id), task wiring intact.
        assert run.kind is RunKind.QUEUED
        assert run.is_queued is True
        assert run.task_id == "task-7"
        assert run.user_message_id == "msg-1"
        assert run.conversation_id == "conv-1"
        assert run.user == {"user_id": "u1", "email": "u1@x.com", "name": "Uno", "timezone": None}

        # The popped item's stale stream_id is replaced by the fresh queued one.
        assert prepared.configurable["stream_id"] == run.stream_id
        assert run.stream_id != "old-stream"
        assert prepared.task == "summarize my inbox"

        # Lock overwritten with the new run's value BEFORE returning, via the RAW
        # client.set — the value must be the unquoted lock string get_lock_state
        # reads back, NOT redis_cache.set's JSON-encoded (quoted) form.
        redis.client.set.assert_awaited_once()
        args, kwargs = redis.client.set.await_args
        assert args[0] == "executor:busy:conv-1"
        assert args[1] == build_lock_value(run.stream_id, "task-7")
        assert kwargs["ex"] == EXECUTOR_BUSY_TTL

        # Session registered as QUEUED with the executor pre-marked spawned
        # (queued runs have no chat_service to register for them).
        session = get_session(run.stream_id)
        assert session is not None
        assert session.kind is RunKind.QUEUED
        assert session.executor_spawned is True

        # Stream progress started + frontend told to open a live subscription.
        sm.start_stream.assert_awaited_once()
        ws.broadcast_to_user.assert_awaited_once()
        event = ws.broadcast_to_user.await_args.args[1]
        assert event["type"] == "executor.stream_started"
        assert event["stream_id"] == run.stream_id
        assert event["task_id"] == "task-7"

    async def test_workflow_context_survives_the_queue(self) -> None:
        item = _queue_item(
            configurable={
                "user_id": "u1",
                "workflow_id": "wf-1",
                "workflow_title": "Digest",
                "workflow_notify_on_completion": False,
            }
        )
        with (
            patch.object(eq, "redis_cache") as redis,
            patch.object(eq, "StreamManager") as sm,
            patch.object(eq, "websocket_manager") as ws,
        ):
            redis.client.lpop = AsyncMock(return_value=item)
            redis.client.set = AsyncMock()
            sm.start_stream = AsyncMock()
            ws.broadcast_to_user = AsyncMock()

            prepared = await pop_next_queued_run("conv-1")

        assert prepared is not None
        assert prepared.run.workflow_id == "wf-1"
        assert prepared.run.workflow_notify_on_completion is False
        assert prepared.run.executor_owns_tool_data is True


class TestLockOwnership:
    """The ownership contract behind safe finalize handoffs (BUG C fix)."""

    async def test_matching_value_is_ours(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.get = AsyncMock(return_value=build_lock_value("s1", "t1"))
            assert await get_lock_state("conv-1", "s1", "t1") is LockState.OURS

    async def test_missing_lock_is_free(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.get = AsyncMock(return_value=None)
            assert await get_lock_state("conv-1", "s1", "t1") is LockState.FREE

    async def test_other_value_is_foreign(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.get = AsyncMock(return_value=build_lock_value("other", "t9"))
            assert await get_lock_state("conv-1", "s1", "t1") is LockState.FOREIGN

    async def test_a_run_without_a_task_id_still_owns_its_own_lock(self) -> None:
        """A chat run carries no task_id, so its lock value is ``stream:`` with the
        task half EMPTY. Comparing against anything else makes every such run
        read its own lock as foreign and refuse to release it."""
        with patch.object(eq, "redis_cache") as redis:
            redis.client.get = AsyncMock(return_value="s1:")
            assert await get_lock_state("conv-1", "s1", None) is LockState.OURS

    async def test_a_missing_task_id_does_not_match_a_lock_that_names_one(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.get = AsyncMock(return_value="s1:t1")
            assert await get_lock_state("conv-1", "s1", None) is LockState.FOREIGN

    async def test_release_deletes_only_when_owned(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.get = AsyncMock(return_value=build_lock_value("s1", "t1"))
            redis.delete = AsyncMock()
            await release_lock_if_owned("conv-1", "s1", "t1")
            redis.delete.assert_awaited_once()

    async def test_release_never_deletes_a_foreign_lock(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.get = AsyncMock(return_value=build_lock_value("other", "t9"))
            redis.delete = AsyncMock()
            await release_lock_if_owned("conv-1", "s1", "t1")
            redis.delete.assert_not_awaited()


class TestReclaimStrandedTask:
    """The post-release recheck that closes the strand window (BUG A fix)."""

    async def test_empty_queue_reclaims_nothing(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.llen = AsyncMock(return_value=0)
            redis.client.set = AsyncMock()
            assert await reclaim_stranded_task("conv-1") is None
            redis.client.set.assert_not_awaited()  # never touches the lock

    async def test_lost_nx_claim_backs_off(self) -> None:
        """A concurrent call_executor acquired the lock first — its finalize
        will drain the queue, so reclaim must yield rather than trample."""
        with patch.object(eq, "redis_cache") as redis:
            redis.client.llen = AsyncMock(return_value=1)
            redis.client.set = AsyncMock(return_value=None)  # NX lost
            assert await reclaim_stranded_task("conv-1") is None

    async def test_won_claim_pops_and_returns_the_stranded_task(self) -> None:
        sentinel = object()
        with (
            patch.object(eq, "redis_cache") as redis,
            patch.object(
                eq, "pop_next_queued_run", new_callable=AsyncMock, return_value=sentinel
            ) as pop,
        ):
            redis.client.llen = AsyncMock(return_value=1)
            redis.client.set = AsyncMock(return_value=True)  # NX won
            assert await reclaim_stranded_task("conv-1") is sentinel
            pop.assert_awaited_once_with("conv-1")

    async def test_won_claim_with_raced_empty_queue_frees_the_sentinel(self) -> None:
        with (
            patch.object(eq, "redis_cache") as redis,
            patch.object(eq, "pop_next_queued_run", new_callable=AsyncMock, return_value=None),
        ):
            redis.client.llen = AsyncMock(return_value=1)
            redis.client.set = AsyncMock(return_value=True)
            redis.delete = AsyncMock()
            assert await reclaim_stranded_task("conv-1") is None
            redis.delete.assert_awaited_once()  # don't block call_executor


class TestEnqueueTask:
    async def test_serializes_owned_keys_and_drops_unsafe_values(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.rpush = AsyncMock()
            redis.client.expire = AsyncMock()

            await enqueue_task(
                queue_key="executor:queue:conv-1",
                task="do it",
                task_id="task-1",
                configurable={
                    "user_id": "u1",
                    "workflow_id": "wf-1",
                    # Not declared on AgentConfigurable — LangGraph's own runtime
                    # keys look like this and must never reach the queue item.
                    "not_owned": "dropped",
                    # Declared, but holding something JSON cannot carry.
                    "model_kwargs": {"provider": object()},
                },
                conversation_id="conv-1",
                user_message_id="msg-1",
            )

            payload = json.loads(redis.client.rpush.await_args.args[1])
            assert payload["task"] == "do it"
            assert payload["configurable"] == {"user_id": "u1", "workflow_id": "wf-1"}
            assert payload["user_message_id"] == "msg-1"
            redis.client.expire.assert_awaited_once_with(
                "executor:queue:conv-1", EXECUTOR_QUEUE_TTL
            )


class TestBuildRunItem:
    """``build_run_item`` is the single serialized shape written by both the
    plain queue enqueue and the HIL pause store — fields must default so a
    plain queue item never accidentally carries resume-only identity."""

    def test_omits_bot_message_id_by_default(self) -> None:
        item = build_run_item(
            task="do it",
            task_id="task-1",
            configurable={"user_id": "u1"},
            conversation_id="conv-1",
            user_message_id="msg-1",
        )
        assert item["bot_message_id"] is None

    def test_carries_bot_message_id_when_a_pause_supplies_it(self) -> None:
        item = build_run_item(
            task="do it",
            task_id="task-1",
            configurable={"user_id": "u1"},
            conversation_id="conv-1",
            user_message_id="msg-1",
            bot_message_id="orig-msg-1",
        )
        assert item["bot_message_id"] == "orig-msg-1"


class TestPrepareRunFromItemResumeIdentity:
    """A HIL resume re-dispatches through the same ``prepare_run_from_item``
    the queue pop uses — the resumed run must inherit the original bot
    message id from the stored item so its result can reconcile onto it."""

    async def test_bot_message_id_threads_into_the_resumed_run(self) -> None:
        item = build_run_item(
            task="continue the task",
            task_id="task-1",
            configurable={"user_id": "u1"},
            conversation_id="conv-1",
            user_message_id="msg-1",
            bot_message_id="orig-msg-1",
        )
        with (
            patch.object(eq, "redis_cache") as redis,
            patch.object(eq, "StreamManager") as sm,
            patch.object(eq, "websocket_manager") as ws,
        ):
            redis.client.set = AsyncMock()
            sm.start_stream = AsyncMock()
            ws.broadcast_to_user = AsyncMock()

            prepared = await prepare_run_from_item("conv-1", item)

        assert prepared is not None
        assert prepared.run.bot_message_id == "orig-msg-1"
        assert prepared.run.kind is RunKind.QUEUED  # shares the queue's re-dispatch path

        # The client folds the new stream into the ORIGINAL turn's message
        # instead of opening a second placeholder, so the id has to reach the
        # browser on the stream_started event too — not just the run object.
        event = ws.broadcast_to_user.await_args.args[1]
        assert event["bot_message_id"] == "orig-msg-1"

    async def test_plain_queued_item_has_no_bot_message_id(self) -> None:
        item = build_run_item(
            task="do it",
            task_id="task-1",
            configurable={"user_id": "u1"},
            conversation_id="conv-1",
            user_message_id="msg-1",
        )
        with (
            patch.object(eq, "redis_cache") as redis,
            patch.object(eq, "StreamManager") as sm,
            patch.object(eq, "websocket_manager") as ws,
        ):
            redis.client.set = AsyncMock()
            sm.start_stream = AsyncMock()
            ws.broadcast_to_user = AsyncMock()

            prepared = await prepare_run_from_item("conv-1", item)

        assert prepared is not None
        assert prepared.run.bot_message_id is None

        # Present and null rather than absent: the client branches on the key,
        # so a plain queued run must say "open a fresh placeholder" explicitly.
        event = ws.broadcast_to_user.await_args.args[1]
        assert event["bot_message_id"] is None


class TestSafeConfigurable:
    """What survives a queue hop and a HIL resume.

    A dropped key does not make the re-dispatched run smaller — it makes it a
    *different* run than the one the user started, with no signal that it changed.
    """

    @pytest.mark.regression
    def test_carries_every_gaia_owned_key_including_non_scalars(self) -> None:
        configurable: AgentConfigurable = {
            "thread_id": "t",
            "conversation_id": "c",
            "user_id": "u",
            # THE model selection. Dropping it made a queued run resolve a fresh
            # lane instead of continuing the one the user's turn started on.
            "lane": {
                "provider": "openrouter",
                "model": "deepseek/deepseek-v4-flash-0731",
                "reasoning": {"effort": "low"},
                # The OpenRouter first-party pin. Dropping it load-balances the
                # queued run onto throttled resellers — the exact 429s it prevents.
                "provider_pin": {"provider": {"only": ["deepseek"]}},
                "max_input_tokens": 1_000_000,
            },
            "provider": "openrouter",
            "model": "deepseek/deepseek-v4-flash-0731",
            "model_kwargs": {"provider": {"only": ["deepseek"]}},
            "reasoning": {"effort": "low"},
            "plan_type": "pro",
            # The per-request token ceiling keys on this; a fresh id resets the
            # ceiling mid-conversation.
            "root_request_id": "rr-1",
            # The HIL intent judge grounds gated tool calls against these. A
            # resumed run that lost them judges against nothing — on the one path
            # where HIL is the whole point.
            "user_messages": ["send the invoice to bob"],
            "langfuse_trace_id": "tr-1",
        }

        assert safe_configurable(configurable) == configurable

    def test_drops_langgraph_runtime_keys(self) -> None:
        configurable = {
            "thread_id": "t",
            "checkpoint_ns": "ns",
            "__pregel_runtime": object(),
        }

        assert safe_configurable(cast(AgentConfigurable, configurable)) == {"thread_id": "t"}

    def test_drops_the_run_scoped_hil_replay_flag(self) -> None:
        configurable = {"thread_id": "t", "hil_resume_replay": True}

        assert safe_configurable(cast(AgentConfigurable, configurable)) == {"thread_id": "t"}

    def test_warns_and_drops_a_value_that_cannot_be_serialized(self) -> None:
        configurable = {"thread_id": "t", "model_kwargs": {"provider": object()}}

        with patch.object(eq.log, "warning") as warn:
            kept = safe_configurable(cast(AgentConfigurable, configurable))

        assert kept == {"thread_id": "t"}
        assert warn.call_count == 1
        assert warn.call_args.kwargs["configurable_key"] == "model_kwargs"
