"""The gate that keeps a reply's first text ahead of background writes.

A conversation step opens the gate when its reply's first text is committed (or
the attempt ends), and background writers that would otherwise race the first
text wait on it. A writer spawned outside any step sees no gate and runs at
once, so nothing else is delayed.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_gate: ContextVar[asyncio.Event | None] = ContextVar("conversation_first_text_gate", default=None)


@contextmanager
def first_text_gate() -> Iterator[None]:
    """Hold a step's gate: writers spawned inside wait until the gate is opened.

    The gate opens when the step commits its reply's first text, or when the
    attempt ends (the ``finally``), so a reply that shows nothing never stalls a writer.
    """
    event = asyncio.Event()
    token = _gate.set(event)
    try:
        yield
    finally:
        event.set()
        _gate.reset(token)


def open_hot_path() -> None:
    """Open the enclosing gate, letting background writers proceed."""
    event = _gate.get()
    if event is not None:
        event.set()


async def await_hot_path() -> None:
    """Wait until the enclosing step has shown its first text, or its attempt ended."""
    event = _gate.get()
    if event is not None:
        await event.wait()
