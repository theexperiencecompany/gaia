"""E2E: work handed to an executor after its last model call is answered even when the run's finish save fails.

Real: the send route, the step and the comms graph with its real call_executor, the executor
graph, its run and finalize, the busy lock, the inbox and the carry run, on real Mongo, Redis
and the Postgres checkpointer. Substituted: both graphs' model (scripted), the tool store,
the memory engine and the WebSocket fan-out (the e2e step stack), and the first run's finish
save, which fails (or is cancelled) on purpose.

Not exercised: a real LLM, and a real Mongo outage (the save is made to fail in process).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from httpx import AsyncClient
import pytest

from app.agents.core.background import executor_runner
from app.agents.core.background.executor_queue import release_lock_if_owned
from app.agents.core.background.executor_runner import deliver_to_executor
from app.models.conversation_log_models import Reply, WorkFinished, WorkOutcome
from app.models.user_models import AuthenticatedUser
from app.services.conversation.work_log import WorkReport, record_work_finished
from shared.py.wide_events import BOUNDARY_FAILURE_MESSAGE
from tests.e2e._harness.background import (
    LIVE_EXECUTOR_TASK_NAME,
    drain_background_runs,
    tasks_named,
)
from tests.e2e._harness.graph_run import call
from tests.e2e._harness.step_stack import OpenStack, entries_of, replayed
from tests.helpers import WideEventRecorder

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("conversation_indexes")]

ASK = "clean my inbox"
LATE_ASK = "also check the spam folder"
CLEANED = "Inbox cleaned."
SPAM_CHECKED = "Spam folder checked: two newsletters, nothing else."
NARRATED = "Your spam folder only had two newsletters."
_SAVE_SECONDS = 30.0


class _FirstFinishSave:
    """The first run's finish save, which fails as the test says; every later save is the real one."""

    def __init__(self, fail: Callable[[], Awaitable[None]]) -> None:
        self._fail = fail
        self.failed = False

    async def __call__(
        self,
        conversation_id: str,
        user_id: str,
        task_id: str,
        outcome: WorkOutcome,
        report: WorkReport,
        *,
        continued_by_decision: bool = False,
    ) -> None:
        if not self.failed:
            self.failed = True
            await self._fail()
        await record_work_finished(
            conversation_id,
            user_id,
            task_id,
            outcome,
            report,
            continued_by_decision=continued_by_decision,
        )


class _LateWork:
    """Hand the running executor more work as its last model call has ended, before its lock frees."""

    def __init__(self, user: AuthenticatedUser) -> None:
        self._user = user
        self.handed = False

    async def __call__(self, conversation_id: str, stream_id: str, task_id: str | None) -> None:
        if not self.handed:
            self.handed = True
            await deliver_to_executor(conversation_id, self._user, LATE_ASK)
        await release_lock_if_owned(conversation_id, stream_id, task_id)


async def _raise() -> None:
    raise ConnectionError("mongo is unreachable")


def _executor() -> list[Any]:
    return [CLEANED, CLEANED, SPAM_CHECKED, SPAM_CHECKED]


def _comms() -> list[Any]:
    return [call("call_executor", {"task": ASK}, call_id="tc_exec"), "On it.", NARRATED]


async def _send(client: AsyncClient, conversation_id: str) -> None:
    sent = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message_id": str(uuid4()), "text": ASK},
    )
    assert sent.status_code == 202, sent.text


def _failed_runs(recorder: WideEventRecorder) -> list[dict[str, Any]]:
    return [
        event
        for event in recorder.events
        if event.get("task") == "executor_run" and event.get("outcome") != "success"
    ]


async def _the_late_work_is_answered(
    conversation_id: str, owner: AuthenticatedUser, executor_prompts: list[list[Any]]
) -> None:
    # Each run answers, then answers again past the executor's finish check.
    read = [LATE_ASK in " ".join(str(m.content) for m in prompt) for prompt in executor_prompts]
    assert read == [False, False, True, True], "no run read the work handed over late"
    shown = await replayed(conversation_id, owner.user_id)
    assert [f.outcome for f in entries_of(shown, WorkFinished)] == [WorkOutcome.DONE]
    assert NARRATED in [reply.text for reply in entries_of(shown, Reply)]


async def test_late_work_is_answered_when_the_runs_finish_save_raises(
    open_stack: OpenStack, owner: AuthenticatedUser, client: AsyncClient
) -> None:
    conversation_id = str(uuid4())
    save = _FirstFinishSave(_raise)
    recorder = WideEventRecorder()
    with (
        patch.object(executor_runner, "record_work_finished", save),
        patch.object(executor_runner, "release_lock_if_owned", _LateWork(owner)),
        patch("shared.py.wide_events._loguru", recorder),
    ):
        async with open_stack(executor=_executor(), comms=_comms()) as stack:
            await _send(client, conversation_id)
            await drain_background_runs()

    assert save.failed
    await _the_late_work_is_answered(conversation_id, owner, stack.executor_model.prompts)
    [failed] = _failed_runs(recorder)
    assert failed["outcome"] == "failed"
    boundary = [e for e in failed["errors"] if e["msg"] == BOUNDARY_FAILURE_MESSAGE]
    assert [(e["error_type"], e["error"]) for e in boundary] == [
        ("ConnectionError", "mongo is unreachable")
    ]


async def test_late_work_is_answered_when_the_run_is_cancelled_during_its_finish_save(
    open_stack: OpenStack, owner: AuthenticatedUser, client: AsyncClient
) -> None:
    conversation_id = str(uuid4())
    saving = asyncio.Event()

    async def _hang() -> None:
        saving.set()
        await asyncio.Event().wait()

    save = _FirstFinishSave(_hang)
    recorder = WideEventRecorder()
    with (
        patch.object(executor_runner, "record_work_finished", save),
        patch.object(executor_runner, "release_lock_if_owned", _LateWork(owner)),
        patch("shared.py.wide_events._loguru", recorder),
    ):
        async with open_stack(executor=_executor(), comms=_comms()) as stack:
            await _send(client, conversation_id)
            async with asyncio.timeout(_SAVE_SECONDS):
                await saving.wait()
            [run] = tasks_named(LIVE_EXECUTOR_TASK_NAME)
            run.cancel()
            await drain_background_runs()

    assert run.cancelled()
    await _the_late_work_is_answered(conversation_id, owner, stack.executor_model.prompts)
    [cancelled] = _failed_runs(recorder)
    assert cancelled["outcome"] == "cancelled"
