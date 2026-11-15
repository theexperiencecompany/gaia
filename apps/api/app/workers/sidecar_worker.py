"""Second arq Workers, each on its own queue, run inside the main worker's process.

ARQ gives every job a worker starts an in-progress key that lives for the longest
function timeout on that worker, and a job whose worker died is not picked up again
until the key expires. A queue whose jobs must neither wait behind the main queue's
long runs nor share their deadlines gets a Worker of its own, with its own slots.
"""

import asyncio
from collections.abc import MutableMapping
from dataclasses import dataclass
import signal
from typing import TypedDict

from arq.worker import Worker

from app.constants.log_tags import LogTag
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log

#: Where the running sidecar workers live in the main worker's ctx.
SIDECAR_WORKERS_CTX_KEY = "sidecar_workers"


@dataclass(frozen=True)
class RunningSidecarWorker:
    """A sidecar queue's Worker and the task serving it."""

    worker: Worker
    task: asyncio.Task[None]


class _SignalOptions(TypedDict):
    """The arq Worker option that decides who owns SIGTERM/SIGINT."""

    handle_signals: bool


# The main worker owns the process's signals. arq reads the flag only for truth, so a
# None here is the same worker: the one mutant of this line is equivalent.
SIGNALS_STAY_WITH_MAIN_WORKER: _SignalOptions = {"handle_signals": False}  # pragma: no mutate


def start_sidecar_worker(ctx: MutableMapping[str, object], name: str, worker: Worker) -> None:
    """Start serving the worker's queue beside the main worker, once the process is ready."""
    task = spawn_background_task(worker.async_run(), name=name, on_done=_stop_process_if_it_ended)
    running = ctx.setdefault(SIDECAR_WORKERS_CTX_KEY, [])
    if not isinstance(running, list):
        raise TypeError(f"ctx[{SIDECAR_WORKERS_CTX_KEY!r}] is not the list of running workers")
    running.append(RunningSidecarWorker(worker=worker, task=task))


async def stop_sidecar_workers(ctx: MutableMapping[str, object]) -> None:
    """Cancel every sidecar worker's jobs (each ends through its cancel path) and close it."""
    running: object = ctx.pop(SIDECAR_WORKERS_CTX_KEY, [])
    if not isinstance(running, list):
        raise TypeError(f"ctx[{SIDECAR_WORKERS_CTX_KEY!r}] is not the list of running workers")
    for sidecar in running:
        await sidecar.worker.close()
        # close() only cancels a run that had got as far as starting its poll loop.
        sidecar.task.cancel()
    if running:
        await asyncio.wait({sidecar.task for sidecar in running})


def _stop_process_if_it_ended(task: asyncio.Task[None]) -> None:
    """Shut the whole worker down when a sidecar worker stops on its own.

    A process whose sidecar worker died would keep running every other job while
    that queue goes unserved; stopping it lets the orchestrator restart both.
    """
    if task.cancelled():
        return
    log.error(
        f"{LogTag.WORKER} Sidecar worker stopped; shutting the worker down",
        sidecar=task.get_name(),
    )
    signal.raise_signal(signal.SIGTERM)
