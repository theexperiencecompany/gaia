"""The comms turn-start sections for work running beside the chat: background executor and browser task.

The executor block is how comms knows whether its background work is really
running. It reads the busy lock, the holder's liveness and the background
subagents over a real (fake) Redis, so these tests pin the states the lock can
actually be in:

* a live holder reads as running;
* a holder whose process died reads NOT running (it once read "STILL RUNNING"
  for the lock's whole 30-minute TTL, so a retry was answered "already on it");
* no holder reads "nothing is running", so a stale hand-off in history is never
  taken as live work.

The browser block tells comms what the chat's browser task is doing, and only
on turns answering the user's own message.
"""

from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest
from tests.browser_factories import make_browser_job_state
from tests.helpers import captured_wide_event

from app.agents.context import live_work
from app.agents.context.live_work import build_browser_task_block, build_executor_status_block
from app.agents.context.section_context import ExecutionMode, SectionContext
from app.agents.context.tiers import AgentTier
from app.agents.core.background.executor_queue import build_lock_value, hold_run_alive
from app.agents.core.background.running_registry import RunningSubagents
from app.constants.cache import (
    EXECUTOR_BUSY_PREFIX,
    EXECUTOR_BUSY_TTL,
    EXECUTOR_DEAD_HOLDER_MIN_AGE_SECONDS,
)
from app.constants.chat import ConversationSource
from app.constants.log_tags import LogTag
from app.models.agent_models import RunningSubagent
from app.schemas.browser import NewHandoff
from app.schemas.browser_job import BrowserJobState, BrowserJobStatus, BrowserJobStopped
from app.services.browser.handoff import bot_chat_address, create_pending_handoff
from app.services.browser.jobs import put_job_state, record_ending, set_latest_job

pytestmark = pytest.mark.unit

CONV = "conv-1"
USER = "user-1"
LOCK_KEY = f"{EXECUTOR_BUSY_PREFIX}{CONV}"
IDLE_TEXT = (
    "No background work is running right now. Every earlier hand-off in this chat has "
    "finished or stopped, even one whose result you have not seen."
)


def _ctx(
    *,
    conversation_id: str | None = CONV,
    user_id: str | None = USER,
    source: str | None = None,
    execution_mode: ExecutionMode = "interactive",
) -> SectionContext:
    return SectionContext(
        tier=AgentTier.COMMS,
        conversation_id=conversation_id,
        user_id=user_id,
        source=source,
        execution_mode=execution_mode,
    )


# ── Background executor ──────────────────────────────────────────────


async def _hold_live_lock(client: fakeredis.aioredis.FakeRedis, task_id: str) -> None:
    value = build_lock_value("s1", task_id)
    await client.set(LOCK_KEY, value, ex=EXECUTOR_BUSY_TTL)
    await hold_run_alive(CONV, value)


async def _hold_dead_lock(client: fakeredis.aioredis.FakeRedis, task_id: str) -> None:
    """Hold a lock older than a holder takes to start renewing, with no liveness: its process died."""
    age = EXECUTOR_DEAD_HOLDER_MIN_AGE_SECONDS + 5
    await client.set(LOCK_KEY, build_lock_value("s1", task_id), ex=EXECUTOR_BUSY_TTL - age)


async def _claim_subagent(subagent_id: str) -> None:
    await RunningSubagents(CONV).claim(
        RunningSubagent(
            subagent_id=subagent_id,
            subagent_thread_id=f"t-{subagent_id}",
            integration_id="gmail",
            agent_name="gmail_agent",
            task_summary="archive promos",
            started_at="2026-10-12T10:00:00+00:00",
            stream_id="s-sub",
            dispatched_by="s1",
        )
    )


async def test_a_live_run_reads_as_running(fake_redis: fakeredis.aioredis.FakeRedis) -> None:
    await _hold_live_lock(fake_redis, "task-123")

    block = await build_executor_status_block(_ctx())

    assert "running right now (task_id: task-123)" in block
    assert "has not arrived" in block


@pytest.mark.regression
async def test_a_dead_holder_reads_as_not_running(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await _hold_dead_lock(fake_redis, "task-7")

    block = await build_executor_status_block(_ctx())

    assert "No background work is running" in block
    assert "task-7" in block
    assert "stopped before it finished" in block


@pytest.mark.regression
async def test_no_holder_reads_as_every_handoff_ended(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    assert await build_executor_status_block(_ctx()) == IDLE_TEXT


async def test_every_status_states_facts_and_leaves_the_call_to_comms(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    # The comms prompt explains how call_executor behaves; the block only says what is true now.
    idle = await build_executor_status_block(_ctx())
    await _hold_dead_lock(fake_redis, "task-1")
    dead = await build_executor_status_block(_ctx())
    await _hold_live_lock(fake_redis, "task-1")
    running = await build_executor_status_block(_ctx())

    assert len({idle, dead, running}) == 3
    for block in (idle, dead, running):
        assert "do not" not in block.lower()
        assert "call_executor" not in block


async def test_background_subagents_still_working_read_as_running(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await _claim_subagent("sa-1")

    block = await build_executor_status_block(_ctx())

    assert block.startswith("Background work is running right now")


async def test_a_holder_without_a_task_id_is_named_unknown(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await _hold_live_lock(fake_redis, "")

    assert "(task_id: unknown)" in await build_executor_status_block(_ctx())


async def test_progress_is_appended_only_while_the_run_holds_the_lock(
    fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Progress content is pinned in test_executor_progress; here, only that the block carries it.
    monkeypatch.setattr(live_work, "describe_progress", lambda _progress: "searched the inbox")
    await _hold_live_lock(fake_redis, "task-1")

    running = await build_executor_status_block(_ctx())
    await fake_redis.delete(LOCK_KEY)
    await _claim_subagent("sa-1")
    subagent_only = await build_executor_status_block(_ctx())

    assert running.endswith("What it has done so far:\nsearched the inbox")
    assert subagent_only.startswith("Background work is running right now")
    assert "done so far" not in subagent_only


async def test_a_chat_without_a_conversation_gets_no_status(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await _hold_live_lock(fake_redis, "task-1")

    assert await build_executor_status_block(_ctx(conversation_id=None)) == ""


async def test_a_failing_status_read_yields_nothing_and_says_why(
    fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        live_work, "read_executor_activity", AsyncMock(side_effect=ConnectionError("down"))
    )

    async with captured_wide_event() as event:
        block = await build_executor_status_block(_ctx())

    assert block == ""
    [logged] = [e for e in event["errors"] if "Executor status unavailable" in e["msg"]]
    assert logged["msg"] == f"{LogTag.AGENT} Executor status unavailable"
    assert logged["error_type"] == "ConnectionError"


# ── Browser task ─────────────────────────────────────────────────────


def _job(job_id: str, task: str) -> BrowserJobState:
    return make_browser_job_state(
        job_id,
        status=BrowserJobStatus.RUNNING,
        task=task,
        conversation_id=CONV,
        user_id=USER,
        in_background=True,
    )


async def _running(job_id: str, task: str) -> None:
    await set_latest_job(CONV, job_id)
    await put_job_state(_job(job_id, task))


async def test_a_running_task_is_wrapped_in_its_tag(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await _running("job-1", "book a table for two")

    block = await build_browser_task_block(_ctx())

    assert block == "<browser_task>\nRunning. Task: book a table for two\n</browser_task>\n"


async def test_a_paused_task_says_what_it_waits_on(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await _running("job-1", "book a table for two")
    await create_pending_handoff(
        "h1",
        NewHandoff(
            job_id="job-1",
            user_id=USER,
            conversation_id=CONV,
            reason="Sign in to opentable.com",
            reply_to=CONV,
        ),
    )

    block = await build_browser_task_block(_ctx())

    assert "Paused" in block
    assert "Sign in to opentable.com" in block
    assert "Running" not in block


async def test_an_ended_task_leaves_no_block(fake_redis: fakeredis.aioredis.FakeRedis) -> None:
    await _running("job-1", "book a table for two")
    await record_ending("job-1", BrowserJobStopped())

    assert await build_browser_task_block(_ctx()) == ""


async def test_a_background_turn_gets_no_block(fake_redis: fakeredis.aioredis.FakeRedis) -> None:
    await _running("job-1", "book a table for two")

    assert await build_browser_task_block(_ctx()) != ""
    assert await build_browser_task_block(_ctx(execution_mode="background")) == ""


@pytest.mark.parametrize(
    "missing", [{"conversation_id": None}, {"user_id": None}], ids=["conversation", "user"]
)
async def test_a_turn_without_its_chat_or_user_gets_no_block(
    fake_redis: fakeredis.aioredis.FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
    missing: dict[str, None],
) -> None:
    read = AsyncMock()
    monkeypatch.setattr(live_work, "chat_browser_tasks", read)

    assert await build_browser_task_block(_ctx(**missing)) == ""
    read.assert_not_awaited()


async def test_a_failed_read_yields_nothing_and_says_why(
    fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        live_work, "chat_browser_tasks", AsyncMock(side_effect=ConnectionError("redis down"))
    )

    async with captured_wide_event() as event:
        block = await build_browser_task_block(_ctx())

    assert block == ""
    [logged] = [e for e in event["errors"] if "Browser task status unavailable" in e["msg"]]
    assert logged["msg"] == f"{LogTag.BROWSER} Browser task status unavailable"
    assert logged["error_type"] == "ConnectionError"


async def test_a_paused_run_a_newer_run_displaced_from_the_bot_chat_is_still_described(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """The user's bot chat is shared by the runs they start from any chat; the newer one takes its latest key."""
    dm = bot_chat_address(ConversationSource.TELEGRAM, USER)
    for job_id, task in (("job-old", "book a table"), ("job-new", "buy a lamp")):
        await set_latest_job(dm, job_id)
        await put_job_state(_job(job_id, task))
    await create_pending_handoff(
        "h-old",
        NewHandoff(
            job_id="job-old",
            user_id=USER,
            conversation_id="conv-group",
            reason="Sign in to opentable.com",
            reply_to=dm,
        ),
    )

    block = await build_browser_task_block(
        _ctx(conversation_id="conv-dm", source=ConversationSource.TELEGRAM.value)
    )

    assert block.splitlines()[1:-1] == [
        "Running. Task: buy a lamp",
        "Paused, waiting for the user to finish a step in the live view: "
        "Sign in to opentable.com. Task: book a table",
    ]
