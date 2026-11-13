"""Drain the detached work a chat turn leaves running, by task name, deterministically."""

from __future__ import annotations

import asyncio

from app.agents.core.background.executor_runner import (
    DETACHED_EXECUTOR_TASK_NAME,
    run_executor_background,
)
from app.agents.core.background.redis_writer import STREAM_PUBLISH_TASK_NAME
from app.agents.core.subagents.delegation import BACKGROUND_SUBAGENT_TASK_NAME
from app.services.hil import resolution
from app.utils import background_tasks

#: call_executor spawns its live run unnamed, so the task carries the coroutine's name.
LIVE_EXECUTOR_TASK_NAME = run_executor_background.__qualname__


def tasks_named(*names: str) -> list[asyncio.Task[object]]:
    """Live background tasks carrying any of names.

    Filtering by name rather than draining the whole keep-alive set: that set
    also holds work which outlives a single turn, so awaiting all of it would
    hang here forever instead of failing a test.
    """
    wanted = set(names)
    return [t for t in background_tasks._background_tasks if t.get_name() in wanted]


async def drain_publishes() -> None:
    """Wait out the fire-and-forget XADDs the background writer scheduled.

    make_redis_stream_writer is a sync callable that schedules each publish
    through spawn_background_task, so reading the log without waiting reads a
    truncated stream.
    """
    while pending := tasks_named(STREAM_PUBLISH_TASK_NAME):
        await asyncio.gather(*pending, return_exceptions=True)


async def drain_background_runs() -> None:
    """Wait out every executor and background-subagent run still in flight, whatever spawned it.

    A background subagent's landing can wake a collection executor run, which can
    hand off again, and HIL's resume set spawns into the same keep-alive set — so
    this loops until all of them are empty. Callers keep their patches open
    across it: a run outliving its doubles would reach the real services.
    """
    while pending := [
        *tasks_named(
            STREAM_PUBLISH_TASK_NAME,
            LIVE_EXECUTOR_TASK_NAME,
            DETACHED_EXECUTOR_TASK_NAME,
            BACKGROUND_SUBAGENT_TASK_NAME,
        ),
        *resolution._resume_tasks,
    ]:
        await asyncio.gather(*pending, return_exceptions=True)
