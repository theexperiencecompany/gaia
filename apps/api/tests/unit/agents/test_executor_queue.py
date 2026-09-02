"""Unit tests for the executor busy lock and detached-run materialization.

There is no queue any more: work handed to a busy executor goes to that
conversation's inbox (``executor_channel``) and the live run absorbs it. What
remains in ``executor_queue`` is the per-conversation busy lock, the
collection-wake claim, and ``prepare_run_from_item`` — the path a HIL resume
rebuilds its run through.

Redis is real (fakeredis) here on purpose. The lock's whole job is atomic
ownership under SET NX with a TTL, and a mock that returns whatever the test
told it to proves nothing about that. It is also the only way to catch the
encoding bug this file pins: a lock written through the JSON-encoding wrapper
comes back quoted, so the run that wrote it reads its own lock as FOREIGN.
"""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest

from app.agents.core.background import executor_queue as eq, session as sess
from app.agents.core.background.executor_queue import (
    QUEUED_STREAM_ID_PREFIX,
    ExecutorRunItem,
    LockState,
    build_lock_value,
    build_run_item,
    claim_collection_wake,
    clear_collection_marker,
    extend_lock_if_owned,
    get_lock_holder,
    get_lock_state,
    is_executor_busy,
    parse_lock_value,
    prepare_run_from_item,
    release_lock_if_owned,
    safe_configurable,
    try_acquire_lock,
)
from app.agents.core.background.session import RunIdentity, RunKind, get_session
from app.constants.cache import EXECUTOR_BUSY_PREFIX, EXECUTOR_BUSY_TTL
from app.constants.executor import (
    EXECUTOR_COLLECT_MARKER_PREFIX,
    EXECUTOR_COLLECT_MARKER_TTL,
)
from app.db.redis import redis_cache
from app.models.agent_models import AgentConfigurable

CONVERSATION = "conv-1"
BUSY_KEY = f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}"
COLLECT_KEY = f"{EXECUTOR_COLLECT_MARKER_PREFIX}{CONVERSATION}"


@pytest.fixture(autouse=True)
def _clean_registry():
    sess._sessions.clear()
    yield
    sess._sessions.clear()


@pytest.fixture
async def redis() -> fakeredis.aioredis.FakeRedis:
    """The real ``redis_cache`` wrapper over a fake server, exactly as production
    reaches it — ``decode_responses=True`` included, since the lock is compared
    as a string."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with patch.object(redis_cache, "redis", client):
        yield client
    await client.aclose()


@pytest.fixture
def stream_side():
    """The two side effects a detached run has outside Redis."""
    with (
        patch.object(eq, "StreamManager") as stream_manager,
        patch.object(eq, "websocket_manager") as websocket,
    ):
        stream_manager.start_stream = AsyncMock()
        websocket.broadcast_to_user = AsyncMock()
        yield SimpleNamespace(stream_manager=stream_manager, websocket=websocket)


def _no_redis() -> Any:
    return patch.object(eq, "redis_cache", SimpleNamespace(client=None))


def _identity(**overrides: Any) -> RunIdentity:
    fields: dict[str, Any] = {
        "stream_id": "",
        "conversation_id": CONVERSATION,
        "kind": RunKind.QUEUED,
        "task_id": "task-7",
        "user_message_id": "msg-1",
    }
    return RunIdentity(**{**fields, **overrides})


def _item(**overrides: Any) -> ExecutorRunItem:
    fields: dict[str, Any] = {
        "task": "summarize my inbox",
        "configurable": {
            "user_id": "u1",
            "email": "u1@x.com",
            "user_name": "Uno",
            # The stream the ORIGINAL turn ran on; it is dead by the time this
            # item is re-dispatched and must never be reused.
            "stream_id": "old-stream",
        },
        "identity": _identity(),
    }
    return build_run_item(**{**fields, **overrides})


class TestLockValue:
    def test_roundtrip(self) -> None:
        value = build_lock_value("stream-1", "task-1")
        assert parse_lock_value(value) == ("stream-1", "task-1")

    def test_missing_stream_id_builds_parseable_value(self) -> None:
        assert parse_lock_value(build_lock_value(None, "task-1")) == ("", "task-1")

    def test_parse_without_separator_returns_value_as_stream(self) -> None:
        assert parse_lock_value("legacy") == ("legacy", "")


class TestAcquireLock:
    """One executor per conversation — the acquisition is what enforces it."""

    async def test_acquire_is_exclusive_and_leaves_the_first_value_intact(self, redis) -> None:
        assert await try_acquire_lock(BUSY_KEY, build_lock_value("s1", "t1")) is True
        assert await try_acquire_lock(BUSY_KEY, build_lock_value("s2", "t2")) is False
        assert await redis.get(BUSY_KEY) == build_lock_value("s1", "t1")

    async def test_a_released_lock_can_be_acquired_again(self, redis) -> None:
        await try_acquire_lock(BUSY_KEY, build_lock_value("s1", "t1"))
        await release_lock_if_owned(CONVERSATION, "s1", "t1")

        assert await try_acquire_lock(BUSY_KEY, build_lock_value("s2", "t2")) is True

    async def test_the_lock_expires_so_a_dead_run_cannot_wedge_the_conversation(
        self, redis
    ) -> None:
        await try_acquire_lock(BUSY_KEY, build_lock_value("s1", "t1"))

        assert await redis.ttl(BUSY_KEY) == EXECUTOR_BUSY_TTL


class TestLockOwnership:
    """The ownership contract behind safe finalize handoffs.

    A stale run's finalize must not free (or extend) a lock a NEWER run now
    holds — that is what let two executors run in one conversation.
    """

    async def test_matching_value_is_ours(self, redis) -> None:
        await redis.set(BUSY_KEY, build_lock_value("s1", "t1"))
        assert await get_lock_state(CONVERSATION, "s1", "t1") is LockState.OURS

    async def test_missing_lock_is_free(self, redis) -> None:
        assert await get_lock_state(CONVERSATION, "s1", "t1") is LockState.FREE

    async def test_other_value_is_foreign(self, redis) -> None:
        await redis.set(BUSY_KEY, build_lock_value("other", "t9"))
        assert await get_lock_state(CONVERSATION, "s1", "t1") is LockState.FOREIGN

    async def test_a_run_without_a_task_id_still_owns_its_own_lock(self, redis) -> None:
        """A chat run carries no task_id, so its lock value is ``stream:`` with the
        task half EMPTY. Comparing against anything else makes every such run
        read its own lock as foreign and refuse to release it."""
        await redis.set(BUSY_KEY, "s1:")
        assert await get_lock_state(CONVERSATION, "s1", None) is LockState.OURS

    async def test_a_missing_task_id_does_not_match_a_lock_that_names_one(self, redis) -> None:
        await redis.set(BUSY_KEY, "s1:t1")
        assert await get_lock_state(CONVERSATION, "s1", None) is LockState.FOREIGN

    async def test_get_lock_holder_reports_the_stored_value(self, redis) -> None:
        await redis.set(BUSY_KEY, build_lock_value("s1", "t1"))
        assert await get_lock_holder(CONVERSATION) == "s1:t1"

    async def test_get_lock_holder_is_none_when_nobody_holds_it(self, redis) -> None:
        assert await get_lock_holder(CONVERSATION) is None

    async def test_release_deletes_only_when_owned(self, redis) -> None:
        await redis.set(BUSY_KEY, build_lock_value("s1", "t1"))

        await release_lock_if_owned(CONVERSATION, "s1", "t1")

        assert await redis.get(BUSY_KEY) is None

    async def test_release_never_deletes_a_foreign_lock(self, redis) -> None:
        await redis.set(BUSY_KEY, build_lock_value("other", "t9"))

        await release_lock_if_owned(CONVERSATION, "s1", "t1")

        assert await redis.get(BUSY_KEY) == build_lock_value("other", "t9")

    async def test_extend_re_arms_our_own_lock(self, redis) -> None:
        """A run parked on a HIL approval outlives its lock's original TTL; if the
        lock lapses a new run takes the thread and discards the checkpoint."""
        await redis.set(BUSY_KEY, build_lock_value("s1", "t1"), ex=5)

        assert await extend_lock_if_owned(CONVERSATION, "s1", "t1", 900) is True
        assert await redis.ttl(BUSY_KEY) == 900

    async def test_extend_refuses_a_foreign_lock(self, redis) -> None:
        await redis.set(BUSY_KEY, build_lock_value("other", "t9"), ex=5)

        assert await extend_lock_if_owned(CONVERSATION, "s1", "t1", 900) is False
        assert await redis.ttl(BUSY_KEY) == 5

    async def test_busy_reports_any_holder_not_just_ours(self, redis) -> None:
        assert await is_executor_busy(CONVERSATION) is False

        await redis.set(BUSY_KEY, build_lock_value("other", "t9"))

        assert await is_executor_busy(CONVERSATION) is True


class TestWithoutRedis:
    """How each answer degrades when Redis cannot be reached.

    These are not defaults, they are decisions: the lock may not block work it
    cannot verify, and nothing may promise a wake-up it cannot dedupe.
    """

    async def test_acquire_allows_execution(self) -> None:
        with _no_redis():
            assert await try_acquire_lock(BUSY_KEY, "s1:t1") is True

    async def test_lock_state_degrades_to_ours(self) -> None:
        with _no_redis():
            assert await get_lock_state(CONVERSATION, "s1", "t1") is LockState.OURS

    async def test_busy_fails_closed(self) -> None:
        """The HIL early decision reads this: "cannot tell" must mean "no
        collector is alive", or a decision is recorded that nobody will act on."""
        with _no_redis():
            assert await is_executor_busy(CONVERSATION) is False

    async def test_extend_reports_that_it_did_not_re_arm(self) -> None:
        with _no_redis():
            assert await extend_lock_if_owned(CONVERSATION, "s1", "t1", 900) is False

    async def test_collection_wake_is_not_claimed(self) -> None:
        with _no_redis():
            assert await claim_collection_wake(CONVERSATION) is False

    async def test_preparing_a_run_yields_nothing(self, stream_side) -> None:
        with _no_redis():
            assert await prepare_run_from_item(CONVERSATION, _item()) is None
        stream_side.stream_manager.start_stream.assert_not_awaited()


class TestCollectionWake:
    """One wake per conversation while the marker is held.

    An executor may end its turn while background subagents are still running.
    Every landing wants to wake someone; without this claim, N landings produce
    N wake-up runs for one pile of results.
    """

    async def test_the_first_caller_claims_and_the_next_is_refused(self, redis) -> None:
        assert await claim_collection_wake(CONVERSATION) is True
        assert await claim_collection_wake(CONVERSATION) is False

    async def test_clearing_the_marker_lets_the_next_landing_wake_again(self, redis) -> None:
        await claim_collection_wake(CONVERSATION)

        await clear_collection_marker(CONVERSATION)

        assert await claim_collection_wake(CONVERSATION) is True

    async def test_the_claim_is_per_conversation(self, redis) -> None:
        assert await claim_collection_wake(CONVERSATION) is True
        assert await claim_collection_wake("conv-2") is True

    async def test_the_marker_expires_so_a_lost_join_cannot_mute_collection(self, redis) -> None:
        """Crash insurance: a run that dies between claiming and joining would
        otherwise suppress every future wake-up for that conversation forever."""
        await claim_collection_wake(CONVERSATION)

        assert await redis.ttl(COLLECT_KEY) == EXECUTOR_COLLECT_MARKER_TTL


class TestBuildRunItem:
    """``build_run_item`` is the single serialized shape a detached run is
    rebuilt from — fields must default so an ordinary item never accidentally
    carries resume-only identity."""

    def test_omits_bot_message_id_by_default(self) -> None:
        item = build_run_item(task="do it", configurable={"user_id": "u1"}, identity=_identity())
        assert item["bot_message_id"] is None

    def test_carries_bot_message_id_when_a_pause_supplies_it(self) -> None:
        item = build_run_item(
            task="do it",
            configurable={"user_id": "u1"},
            identity=_identity(bot_message_id="orig-msg-1"),
        )
        assert item["bot_message_id"] == "orig-msg-1"

    def test_the_stored_configurable_is_the_serializable_subset(self) -> None:
        item = build_run_item(
            task="do it",
            configurable=cast(
                AgentConfigurable,
                {
                    "user_id": "u1",
                    "workflow_id": "wf-1",
                    # Not declared on AgentConfigurable — LangGraph's own runtime
                    # keys look like this and must never reach a stored item.
                    "not_owned": "dropped",
                },
            ),
            identity=_identity(),
        )
        assert item["configurable"] == {"user_id": "u1", "workflow_id": "wf-1"}
        assert item["task_id"] == "task-7"
        assert item["user_message_id"] == "msg-1"
        assert item["conversation_id"] == CONVERSATION


class TestSafeConfigurable:
    """What survives a HIL resume.

    A dropped key does not make the re-dispatched run smaller — it makes it a
    *different* run than the one the user started, with no signal that it changed.
    """

    @pytest.mark.regression
    def test_carries_every_gaia_owned_key_including_non_scalars(self) -> None:
        configurable: AgentConfigurable = {
            "thread_id": "t",
            "conversation_id": "c",
            "user_id": "u",
            # THE model selection. Dropping it made a re-dispatched run resolve a
            # fresh lane instead of continuing the one the user's turn started on.
            "lane": {
                "provider": "openrouter",
                "model": "deepseek/deepseek-v4-flash-0731",
                "reasoning": {"effort": "low"},
                # The OpenRouter first-party pin. Dropping it load-balances the
                # run onto throttled resellers — the exact 429s it prevents.
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


class TestPrepareRunFromItem:
    """Materializing a DETACHED run — one that owns its own stream instead of
    sharing a comms turn's. The HIL approval resume is its main consumer, the
    collection wake-up the other; both re-dispatch a run whose original owner is
    gone, so both SEIZE the lock rather than acquire it."""

    async def test_seizes_the_lock_in_the_form_its_owner_reads_back(
        self, redis, stream_side
    ) -> None:
        """Written with the RAW client, not ``redis_cache.set``: the wrapper
        JSON-encodes the string, and the quoted value never matches the raw read
        in ``get_lock_state`` — so the new run reads its OWN lock as foreign and
        leaves it wedged until the TTL."""
        prepared = await prepare_run_from_item(CONVERSATION, _item())

        assert prepared is not None
        run = prepared.run
        assert await redis.get(BUSY_KEY) == build_lock_value(run.stream_id, "task-7")
        assert await get_lock_state(CONVERSATION, run.stream_id, run.task_id) is LockState.OURS
        assert await redis.ttl(BUSY_KEY) == EXECUTOR_BUSY_TTL

    async def test_takes_the_lock_over_from_the_run_that_is_gone(self, redis, stream_side) -> None:
        await redis.set(BUSY_KEY, build_lock_value("dead-stream", "task-0"))

        prepared = await prepare_run_from_item(CONVERSATION, _item())

        assert prepared is not None
        assert await redis.get(BUSY_KEY) == build_lock_value(prepared.run.stream_id, "task-7")

    async def test_mints_a_fresh_stream_and_overrides_the_items_stale_one(
        self, redis, stream_side
    ) -> None:
        prepared = await prepare_run_from_item(CONVERSATION, _item())

        assert prepared is not None
        assert prepared.run.stream_id.startswith(QUEUED_STREAM_ID_PREFIX)
        assert prepared.run.stream_id != "old-stream"
        assert prepared.configurable["stream_id"] == prepared.run.stream_id
        assert prepared.task == "summarize my inbox"

    async def test_registers_a_session_pre_marked_spawned(self, redis, stream_side) -> None:
        """Nothing else registers one for a detached run — no chat_service turn
        owns it — and an unspawned session reads as "the executor never ran"."""
        prepared = await prepare_run_from_item(CONVERSATION, _item())

        assert prepared is not None
        session = get_session(prepared.run.stream_id)
        assert session is not None
        assert session.executor_spawned is True
        assert prepared.run.kind is RunKind.QUEUED
        assert prepared.run.is_queued is True

    async def test_starts_the_stream_and_tells_the_client_to_subscribe(
        self, redis, stream_side
    ) -> None:
        prepared = await prepare_run_from_item(CONVERSATION, _item())

        assert prepared is not None
        stream_side.stream_manager.start_stream.assert_awaited_once_with(
            stream_id=prepared.run.stream_id, conversation_id=CONVERSATION, user_id="u1"
        )
        user_id, event = stream_side.websocket.broadcast_to_user.await_args.args
        assert user_id == "u1"
        assert event == {
            "type": "executor.stream_started",
            "stream_id": prepared.run.stream_id,
            "conversation_id": CONVERSATION,
            "task_id": "task-7",
            # Present and null rather than absent: the client branches on the
            # key to decide between folding into an existing message and opening
            # a fresh placeholder.
            "bot_message_id": None,
        }

    async def test_an_item_with_no_user_still_prepares_but_announces_nothing(
        self, redis, stream_side
    ) -> None:
        prepared = await prepare_run_from_item(CONVERSATION, _item(configurable={}))

        assert prepared is not None
        stream_side.websocket.broadcast_to_user.assert_not_awaited()

    async def test_carries_the_user_and_workflow_context_from_the_item(
        self, redis, stream_side
    ) -> None:
        prepared = await prepare_run_from_item(
            CONVERSATION,
            _item(
                configurable={
                    "user_id": "u1",
                    "email": "u1@x.com",
                    "user_name": "Uno",
                    "workflow_id": "wf-1",
                    "workflow_title": "Digest",
                    "workflow_notify_on_completion": False,
                }
            ),
        )

        assert prepared is not None
        run = prepared.run
        assert run.user == {"user_id": "u1", "email": "u1@x.com", "name": "Uno", "timezone": None}
        assert run.conversation_id == CONVERSATION
        assert run.task_id == "task-7"
        assert run.user_message_id == "msg-1"
        assert run.workflow_id == "wf-1"
        assert run.workflow_title == "Digest"
        assert run.workflow_notify_on_completion is False
        # No comms consumer attaches this run's cards, so it self-persists.
        assert run.executor_owns_tool_data is True

    async def test_bot_message_id_threads_into_the_resumed_run(self, redis, stream_side) -> None:
        """A HIL resume continues the ORIGINAL turn's message: the resumed run
        and the browser both need that id, or the client opens a second
        placeholder and renders its own tool accordion beside the first."""
        item = _item(identity=_identity(bot_message_id="orig-msg-1"))

        prepared = await prepare_run_from_item(CONVERSATION, item)

        assert prepared is not None
        assert prepared.run.bot_message_id == "orig-msg-1"
        event = stream_side.websocket.broadcast_to_user.await_args.args[1]
        assert event["bot_message_id"] == "orig-msg-1"

    async def test_an_item_without_a_pause_has_no_bot_message_id(self, redis, stream_side) -> None:
        prepared = await prepare_run_from_item(CONVERSATION, _item())

        assert prepared is not None
        assert prepared.run.bot_message_id is None


@pytest.mark.regression
class TestRunItemCarriesWorkflowExecution:
    """The execution id exists only on the workflow task's wide event. A HIL
    resume rebuilds the run in some OTHER context (the approval request, the
    previous run's finalize), so the stored item has to carry it or the resumed
    run's calls are unattributable to the run."""

    async def test_the_item_records_the_execution_in_flight(self) -> None:
        from shared.py.wide_events import WorkflowContext, log, wide_task

        async with wide_task("workflow_execution"):
            log.set(workflow=WorkflowContext(id="wf-9", execution_id="exec-42"))
            item = build_run_item(
                task="do it",
                configurable={"user_id": "u1", "workflow_id": "wf-9"},
                identity=_identity(user_message_id=None),
            )

        assert item["workflow_execution_id"] == "exec-42"

    def test_a_run_supplies_its_own_execution_id_when_pausing(self) -> None:
        item = build_run_item(
            task="do it",
            configurable={"user_id": "u1", "workflow_id": "wf-9"},
            identity=_identity(user_message_id=None),
            workflow_execution_id="exec-42",
        )

        assert item["workflow_execution_id"] == "exec-42"

    async def test_a_resume_outside_any_boundary_still_knows_its_execution(
        self, redis, stream_side
    ) -> None:
        item = build_run_item(
            task="continue the task",
            configurable={"user_id": "u1", "workflow_id": "wf-9"},
            identity=_identity(user_message_id=None),
            workflow_execution_id="exec-42",
        )

        # No wide-event boundary here on purpose: this is the approval
        # request's context, where the workflow task's stamp never existed.
        prepared = await prepare_run_from_item(CONVERSATION, item)

        assert prepared is not None
        assert prepared.run.workflow_id == "wf-9"
        assert prepared.run.workflow_execution_id == "exec-42"
