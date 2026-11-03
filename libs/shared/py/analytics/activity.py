"""What counts as a user using GAIA: the closed set of events that make their day an active one.

Signing up, onboarding, loading a page, hitting the paywall or changing a setting
is not use; sending a message (web, desktop, mobile, voice or a linked bot) or
running a workflow is. config/posthog/actions.json's "Active user (human)" lists
the same events, and a test keeps the two equal.
"""

from shared.py.analytics.catalog.attribution import Actor, Attribution
from shared.py.analytics.catalog.base import AnalyticsEvent, ServerEvent
from shared.py.analytics.catalog.chat import ChatMessageSubmitted
from shared.py.analytics.catalog.workflows import WorkflowExecuted

ACTIVE_USE_EVENTS: frozenset[type[ServerEvent]] = frozenset(
    {ChatMessageSubmitted, WorkflowExecuted}
)


def is_active_use(event: AnalyticsEvent, attribution: Attribution) -> bool:
    """Whether event, done by attribution's actor, is the user using GAIA; agent work never is."""
    return attribution.actor is Actor.USER and type(event) in ACTIVE_USE_EVENTS


__all__ = ["ACTIVE_USE_EVENTS", "is_active_use"]
