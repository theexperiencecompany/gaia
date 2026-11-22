"""Drain the detached work a chat turn leaves running, by task name, deterministically."""

from __future__ import annotations

import asyncio
import io

from app.agents.core.background.executor_runner import (
    DETACHED_EXECUTOR_TASK_NAME,
)
from app.agents.core.subagents.delegation import BACKGROUND_SUBAGENT_TASK_NAME
from app.services.conversation.composition import running_steps
from app.utils import background_tasks

#: call_executor spawns its live run unnamed, so the task carries the coroutine's name.
LIVE_EXECUTOR_TASK_NAME = "run_executor_background"
#: How long one turn's background work may run before the journey fails naming what still runs.
DRAIN_DEADLINE_SECONDS = 120


def tasks_named(*names: str) -> list[asyncio.Task[object]]:
    """Live background tasks carrying any of names.

    Filtering by name rather than draining the whole keep-alive set: that set
    also holds work which outlives a single turn, so awaiting all of it would
    hang here forever instead of failing a test.
    """
    wanted = set(names)
    return [t for t in background_tasks._background_tasks if t.get_name() in wanted]


async def drain_background_runs() -> None:
    """Wait out every conversation step, executor and background-subagent run still in flight.

    A background subagent's landing can wake a collection executor run, which can
    hand off again, and a run's end wakes its conversation's step — so this loops until all of
    them are empty. Callers keep their patches open
    across it: a run outliving its doubles would reach the real services.
    """
    while pending := [
        *tasks_named(
            LIVE_EXECUTOR_TASK_NAME,
            DETACHED_EXECUTOR_TASK_NAME,
            BACKGROUND_SUBAGENT_TASK_NAME,
        ),
        *running_steps(),
    ]:
        done, stuck = await asyncio.wait(pending, timeout=DRAIN_DEADLINE_SECONDS)
        await asyncio.gather(*done, return_exceptions=True)
        if stuck:
            stacks = [_stack_of(task) for task in stuck]
            for task in stuck:
                task.cancel()
            raise AssertionError(
                f"background work still running after {DRAIN_DEADLINE_SECONDS}s:\n"
                + "\n".join(stacks)
            )


def _stack_of(task: asyncio.Task[object]) -> str:
    frames = io.StringIO()
    task.print_stack(file=frames)
    return f"{task.get_name()}:\n{frames.getvalue()}"
