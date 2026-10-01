"""Which Browser-Use sessions run on Obscura: the run that drives one says so.

The engine is a fact the browser host reports when it creates a session, and
the run on that session marks its own context with it. Browser-Use runs every
handler of a run in tasks started from that run, so a patch that works around an
Obscura gap reads the engine of the run it is serving, and a Chrome run keeps
Browser-Use's own behaviour. Nothing outside a run is on Obscura.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from app.constants.browser import BrowserEngine

_engine: ContextVar[BrowserEngine | None] = ContextVar("browser_run_engine", default=None)


@contextmanager
def driving(engine: BrowserEngine) -> Iterator[None]:
    """Mark everything run inside as driving a session on engine."""
    token = _engine.set(engine)
    try:
        yield
    finally:
        _engine.reset(token)


def on_obscura() -> bool:
    """Whether the run this code serves drives an Obscura session."""
    return _engine.get() is BrowserEngine.OBSCURA
