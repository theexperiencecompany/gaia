"""Hedged requests: the first answer of up to two identical calls wins.

A provider's slow tail is not a failure, so a timeout is the wrong signal to
retry on: waiting one out before asking again doubles the cost of every slow
call. Sending the same request again after a short while and taking whichever
answers first bounds the tail at roughly hedge_after plus a normal call.

The losing call is not cancelled: the provider bills a request it already took
whether or not anyone reads the answer, so it runs to its end (within the same
deadline) and its answer is handed to on_late, for metering.
"""

import asyncio
from collections.abc import Awaitable, Callable
from functools import partial
from typing import TypeVar

from app.constants.log_tags import LogTag
from app.utils.background_tasks import guard_task
from shared.py.wide_events import log

T = TypeVar("T")


def _late_answer(on_late: Callable[[T], None], call: asyncio.Task[T]) -> None:
    """Hand a losing call's answer to on_late once it lands; a loser that failed or timed out had none."""
    if call.cancelled():
        return
    failure = call.exception()
    if failure is not None:
        log.info(f"{LogTag.BROWSER} Hedged call lost and failed", error_type=type(failure).__name__)
        return
    on_late(call.result())


async def first_answer(
    call: Callable[[], Awaitable[T]],
    *,
    hedge_after: float,
    deadline: float,
    on_late: Callable[[T], None],
) -> T:
    """Return the first successful result of call, starting one spare call if the first is slow.

    Only slowness starts the spare: an error is the call's own to retry (the
    writer lane already does), and retrying it here too multiplies requests.
    Raises the last error when every call started has failed, and
    TimeoutError when none answers within deadline seconds.
    """

    def start() -> asyncio.Task[T]:
        return asyncio.ensure_future(asyncio.wait_for(call(), timeout=deadline))

    pending: set[asyncio.Task[T]] = {start()}
    spare_left = True
    error: BaseException
    try:
        async with asyncio.timeout(deadline):
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    timeout=hedge_after if spare_left else None,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    failure = task.exception()
                    if failure is None:
                        for loser in pending:
                            loser.add_done_callback(partial(_late_answer, on_late))
                            guard_task(loser)
                        pending = set()
                        return task.result()
                    error = failure
                if not done and spare_left:
                    spare_left = False
                    pending.add(start())
    except TimeoutError:
        raise TimeoutError(f"no answer within {deadline:.0f}s") from None
    finally:
        for task in pending:
            task.cancel()
    # The loop only drains when every call started has failed.
    raise error
