"""The gate that keeps a reply's first text ahead of the writes nothing on its path needs.

A comms attempt holds the gate from its start until its reply opens, or the attempt ends.
Optional writers spawned inside it (the metering ledger) wait on it, so they still run exactly
once, just after the first text; a writer outside any attempt sees no gate and runs at once.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_gate: ContextVar[asyncio.Event | None] = ContextVar("first_text_gate", default=None)


@contextmanager
def first_text_gate() -> Iterator[None]:
    """Hold the gate for writers spawned inside; it opens at the first text, or when the block ends."""
    event = asyncio.Event()
    token = _gate.set(event)
    try:
        yield
    finally:
        event.set()
        _gate.reset(token)


def first_text_shown() -> None:
    """Open the enclosing gate: the reply's first text is out."""
    event = _gate.get()
    if event is not None:
        event.set()


async def after_first_text() -> None:
    """Wait until the enclosing attempt showed its first text or ended; at once outside any attempt."""
    event = _gate.get()
    if event is not None:
        await event.wait()
