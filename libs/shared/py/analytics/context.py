"""The analytics context of the work running now: its attribution and originating PostHog session.

Bound once at each entry point (an HTTP request, a voice session, an ARQ job,
an agent run) and read by the capture functions, which fail when nothing bound
it, so an event can never leave unattributed.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from pydantic import BaseModel, ConfigDict

from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.catalog.properties import Identifier

#: The property PostHog joins an event to a browser session (and its replay) by.
POSTHOG_SESSION_PROPERTY = "$session_id"


class MissingAnalyticsContextError(RuntimeError):
    """An event was captured where no entry point bound an analytics context."""


class AnalyticsContext(BaseModel):
    """Who caused the work running now, and the browser session it came from, if any."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attribution: Attribution
    posthog_session_id: Identifier | None = None

    def acting_as(self, actor: Actor) -> "AnalyticsContext":
        """Return the same run, with the action performed by actor."""
        return self.model_copy(
            update={"attribution": self.attribution.model_copy(update={"actor": actor})}
        )

    def to_properties(self) -> dict[str, object]:
        """Return the properties every attributed event is stamped with."""
        properties: dict[str, object] = self.attribution.model_dump(mode="json")
        if self.posthog_session_id:
            properties[POSTHOG_SESSION_PROPERTY] = self.posthog_session_id
        return properties


def worker_context(trigger: Trigger) -> AnalyticsContext:
    """Return the context of agent work no client started, begun by trigger."""
    return AnalyticsContext(
        attribution=Attribution(actor=Actor.AGENT, trigger=trigger, surface=EntrySurface.WORKER)
    )


_current: ContextVar[AnalyticsContext | None] = ContextVar("analytics_context", default=None)


def current_analytics_context() -> AnalyticsContext:
    """Return the bound context; raise when no entry point bound one."""
    context = _current.get()
    if context is None:
        raise MissingAnalyticsContextError(
            "no analytics context is bound: bind one at the entry point that started this work"
        )
    return context


def bound_analytics_context() -> AnalyticsContext | None:
    """Return the bound context, or None outside every entry point."""
    return _current.get()


@contextmanager
def analytics_context(context: AnalyticsContext) -> Iterator[AnalyticsContext]:
    """Bind context for the block, and for every task spawned inside it."""
    token = _current.set(context)
    try:
        yield context
    finally:
        _current.reset(token)


__all__ = [
    "POSTHOG_SESSION_PROPERTY",
    "AnalyticsContext",
    "MissingAnalyticsContextError",
    "analytics_context",
    "bound_analytics_context",
    "current_analytics_context",
    "worker_context",
]
