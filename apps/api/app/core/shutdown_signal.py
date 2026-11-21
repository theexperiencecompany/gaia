"""The moment this process is asked to stop, raised as SIGINT/SIGTERM arrives.

uvicorn runs the lifespan's shutdown only after every open connection closes, so a stream
that waits for it never ends; streams end on this signal instead, before uvicorn waits.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import signal
import threading
from types import FrameType

_STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM)

SignalHandler = Callable[[int, FrameType | None], object]


@dataclass
class _Installed:
    event: asyncio.Event | None = None
    server_handlers: dict[signal.Signals, SignalHandler] = field(default_factory=dict)


_installed = _Installed()


def _chained(
    loop: asyncio.AbstractEventLoop, requested: asyncio.Event, server_handler: SignalHandler
) -> SignalHandler:
    def raise_requested(signum: int, frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(requested.set)
        server_handler(signum, frame)

    return raise_requested


def install_shutdown_signal() -> None:
    """Chain onto the server's SIGINT/SIGTERM handlers so a stop request also sets shutdown_requested().

    A server off the main thread handles no signals, and a signal with no server handler keeps
    its default; neither has a stop request to chain onto.
    """
    requested = asyncio.Event()
    _installed.event = requested
    if threading.current_thread() is not threading.main_thread():
        return
    loop = asyncio.get_running_loop()
    for stop in _STOP_SIGNALS:
        server_handler = signal.getsignal(stop)
        if callable(server_handler):
            _installed.server_handlers[stop] = server_handler
            signal.signal(stop, _chained(loop, requested, server_handler))


def remove_shutdown_signal() -> None:
    """Hand SIGINT/SIGTERM back to the server's own handlers."""
    for stop, server_handler in _installed.server_handlers.items():
        signal.signal(stop, server_handler)
    _installed.server_handlers.clear()
    _installed.event = None


def shutdown_requested() -> asyncio.Event:
    """Return the event a stop request sets; outside a served process nothing ever sets it."""
    return _installed.event if _installed.event is not None else asyncio.Event()
