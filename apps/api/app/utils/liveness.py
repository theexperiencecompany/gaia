"""Prove a holder alive for as long as it holds something, and stop it once that can no longer be proven."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
import time
from typing import cast

from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log


def keep_proving(
    prove: Callable[[], Awaitable[bool]],
    *,
    every: float,
    give_up_after: float,
    name: str,
    what: str,
    context: Mapping[str, str],
) -> asyncio.Task[None]:
    """Run prove every few seconds beside the calling task until that task ends.

    prove returns False when the liveness is gone for good: the holder is cancelled at once.
    A prove that raises is retried until give_up_after seconds pass unproven, then the holder
    is cancelled before its key can lapse and another process take what it holds.
    """
    # Always set: a function called on the loop runs inside a task.
    holder = cast("asyncio.Task[object]", asyncio.current_task())
    beating = spawn_background_task(
        _beat(prove, every, give_up_after, holder, what, context), name=name
    )
    holder.add_done_callback(lambda _: beating.cancel())
    return beating


async def _beat(
    prove: Callable[[], Awaitable[bool]],
    every: float,
    give_up_after: float,
    holder: asyncio.Task[object],
    what: str,
    context: Mapping[str, str],
) -> None:
    proven_at = time.monotonic()
    while True:
        await asyncio.sleep(every)
        try:
            proven = await prove()
        except Exception as e:  # one failed write must not end the renewal of a live holder
            unproven = time.monotonic() - proven_at
            stopping = unproven >= give_up_after
            log.error(
                "Could not renew a holder's liveness",
                what=what,
                **context,
                unproven_seconds=round(unproven, 1),
                stopping_holder=stopping,
                error_type=type(e).__name__,
                error=str(e),
            )
            if not stopping:
                continue
        else:
            if proven:
                proven_at = time.monotonic()
                continue
            log.error("A holder's liveness lapsed; stopping it", what=what, **context)
        holder.cancel(f"{what} liveness lost")
        return
