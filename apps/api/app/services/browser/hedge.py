"""Hedged requests: the first answer of up to two identical calls wins.

A provider's slow tail is not a failure, so a timeout is the wrong signal to
retry on: waiting one out before asking again doubles the cost of every slow
call. Sending the same request again after a short while and taking whichever
answers first bounds the tail at roughly hedge_after plus a normal call.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


async def first_answer(
    call: Callable[[], Awaitable[T]], *, hedge_after: float, deadline: float
) -> T:
    """Return the first successful result of call, starting one spare call if the first is slow.

    Only slowness starts the spare: an error is the call's own to retry (the
    writer lane already does), and retrying it here too multiplies requests.
    Raises the last error when every call started has failed, and
    TimeoutError when none answers within deadline seconds.
    """
    pending: set[asyncio.Future[T]] = {asyncio.ensure_future(call())}
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
                        return task.result()
                    error = failure
                if not done and spare_left:
                    spare_left = False
                    pending.add(asyncio.ensure_future(call()))
    except TimeoutError:
        raise TimeoutError(f"no answer within {deadline:.0f}s") from None
    finally:
        for task in pending:
            task.cancel()
    # The loop only drains when every call started has failed.
    raise error
