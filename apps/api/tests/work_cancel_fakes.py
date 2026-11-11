"""A conversation with every kind of live work, on real Redis keys, for the stop paths to cancel.

Only the approval stores are faked (Mongo-backed); the executor lock, inbox, subagent
registry and browser job are the real Redis records each stop reads.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

from app.agents.core.background.executor_channel import ExecutorInbox
from app.agents.core.background.running_registry import RunningSubagents
from app.constants.cache import EXECUTOR_BUSY_PREFIX, EXECUTOR_BUSY_TTL
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.models.agent_models import RunningSubagent
from app.schemas.browser_job import BrowserJobStatus
from app.services.browser.jobs import put_job_state, set_latest_job
from tests.browser_factories import make_browser_job_state

EXECUTOR_STREAM = "executor-stream"
EXECUTOR_TASK = "running-task"
SUBAGENT_STREAM = "subagent_s1"
BROWSER_JOB = "job-1"
APPROVAL = "approval-1"
LEDGER_APPROVAL = "ledger-1"


@dataclass(frozen=True)
class ApprovalSeams:
    """The two approval stores' cancel calls, as the stop paths reach them."""

    barrier: AsyncMock
    ledger: AsyncMock


def approval_seams(*, pending: bool) -> Iterator[ApprovalSeams]:
    """Patch both approval cancels; each closes one approval when pending, none otherwise."""
    barrier = AsyncMock(return_value=[APPROVAL] if pending else [])
    ledger = AsyncMock(return_value=[LEDGER_APPROVAL] if pending else [])
    module = "app.agents.core.background.work_cancel"
    with (
        patch(f"{module}.cancel_conversation_approvals", barrier),
        patch(f"{module}.cancel_ledger_approvals", ledger),
    ):
        yield ApprovalSeams(barrier=barrier, ledger=ledger)


async def seed_live_work(conversation_id: str, user_id: str) -> None:
    """Start an executor run with a queued request, a subagent of its own and a browser job."""
    await stream_manager.start_stream(EXECUTOR_STREAM, conversation_id, user_id)
    await redis_cache.client.set(
        f"{EXECUTOR_BUSY_PREFIX}{conversation_id}",
        f"{EXECUTOR_STREAM}:{EXECUTOR_TASK}",
        ex=EXECUTOR_BUSY_TTL,
    )
    await ExecutorInbox(conversation_id).append("queued-task", "and then this")
    assert await RunningSubagents(conversation_id).claim(
        RunningSubagent(
            subagent_id="s1",
            subagent_thread_id=f"spawn_{conversation_id}_s1",
            integration_id="ticker",
            agent_name="ticker_agent",
            task_summary="tick",
            started_at="2026-09-25T00:00:00Z",
            stream_id=SUBAGENT_STREAM,
            dispatched_by="an-earlier-turn",
        )
    )
    await set_latest_job(conversation_id, BROWSER_JOB)
    await put_job_state(
        make_browser_job_state(
            BROWSER_JOB, status=BrowserJobStatus.RUNNING, conversation_id=conversation_id
        )
    )
