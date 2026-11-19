"""The arq Workers that serve their own queues inside the worker process, beside the main one.

A queue of its own keeps one kind of job's concurrency, and the in-progress TTL ARQ derives
from its longest timeout, apart from the shared queue (browser jobs, briefs, scout refreshes).
Each runs as a background task of the main worker: started once the process is ready, closed
first on shutdown, and a queue worker that stops on its own takes the process down with it.
"""

import asyncio
from collections.abc import Callable, Iterable, MutableMapping, Sequence
from dataclasses import dataclass, field
import signal
import socket
from typing import TypedDict

from arq.worker import Function, Worker

from app.constants.log_tags import LogTag
from app.utils.background_tasks import spawn_background_task
from app.workers.config.worker_settings import WorkerSettings
from shared.py.wide_events import log

#: Where the running queue workers live in the main worker's ctx.
QUEUE_WORKERS_CTX_KEY = "queue_workers"


@dataclass(frozen=True)
class RunningQueueWorker:
    """One queue's Worker and the task serving it."""

    worker: Worker
    task: asyncio.Task[None]


@dataclass(frozen=True)
class RunningQueueWorkers:
    """The queue workers this process started, kept in the main worker's ctx."""

    started: list[RunningQueueWorker] = field(default_factory=list)


class _SignalOptions(TypedDict):
    """The arq Worker option that decides who owns SIGTERM/SIGINT."""

    handle_signals: bool


# The main worker owns the process's signals. arq reads the flag only for truth, so a
# None here is the same worker: the one mutant of this line is equivalent.
_SIGNALS_STAY_WITH_MAIN_WORKER: _SignalOptions = {"handle_signals": False}  # pragma: no mutate


def queue_worker_health_key(queue: str) -> str:
    """Return the key this host's worker for queue refreshes while it polls (ARQ's health check)."""
    return f"{queue}:health:{socket.gethostname()}"


def queue_worker(queue: str, functions: Sequence[Function], *, max_jobs: int) -> Worker:
    """Build the arq Worker serving queue, max_jobs at a time; signals stay with the main worker."""
    return Worker(
        functions=functions,
        queue_name=queue,
        redis_settings=WorkerSettings.redis_settings,
        **_SIGNALS_STAY_WITH_MAIN_WORKER,
        max_jobs=max_jobs,
        keep_result=0,
        health_check_interval=WorkerSettings.health_check_interval,
        health_check_key=queue_worker_health_key(queue),
        allow_abort_jobs=True,
    )


def start_queue_workers(
    ctx: MutableMapping[str, object], builders: Iterable[Callable[[], Worker]]
) -> None:
    """Start serving each built Worker's queue beside the main worker, once the process is ready."""
    # In the ctx before the first starts, so a later build that raises leaves the started ones stoppable.
    running = RunningQueueWorkers()
    ctx[QUEUE_WORKERS_CTX_KEY] = running
    for build in builders:
        worker = build()
        task = spawn_background_task(
            worker.async_run(),
            name=f"{worker.queue_name}:worker",
            on_done=_stop_process_if_it_ended,
        )
        running.started.append(RunningQueueWorker(worker=worker, task=task))


async def stop_queue_workers(ctx: MutableMapping[str, object]) -> None:
    """Cancel every queue worker's jobs (each ends through its cancel path) and close it."""
    running = ctx.pop(QUEUE_WORKERS_CTX_KEY, None)
    if not isinstance(running, RunningQueueWorkers) or not running.started:
        # Startup failed before it started any; there is nothing to stop.
        return
    for queue in running.started:
        await queue.worker.close()
        # close() only cancels a run that had got as far as starting its poll loop.
        queue.task.cancel()
    await asyncio.wait({queue.task for queue in running.started})


def _stop_process_if_it_ended(task: asyncio.Task[None]) -> None:
    """Shut the whole worker down when a queue worker stops on its own.

    A process whose queue worker died would keep running every other job while that
    queue's jobs wait unserved; stopping it lets the orchestrator restart them all.
    """
    if task.cancelled():
        return
    log.error(
        f"{LogTag.WORKER} Queue worker stopped; shutting the worker down", task=task.get_name()
    )
    signal.raise_signal(signal.SIGTERM)
