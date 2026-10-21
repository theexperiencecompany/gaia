"""The event catalog: every analytics event GAIA emits, one Pydantic model per event.

Each domain module registers its events on import; CATALOG is the full set,
sorted by event name, that codegen, the tests and the emitters read.
"""

from collections.abc import Mapping

from shared.py.analytics.catalog import (
    agents,
    auth,
    billing,
    bots,
    browser,
    calendars,
    chat,
    devices,
    hil,
    integrations,
    mail,
    marketing,
    memory,
    notifications,
    onboarding,
    reminders,
    search,
    settings,
    support,
    todos,
    ui,
    voice,
    workflows,
)
from shared.py.analytics.catalog.base import AnalyticsEvent, registered_events

DOMAIN_MODULES = (
    agents,
    auth,
    billing,
    bots,
    browser,
    calendars,
    chat,
    devices,
    hil,
    integrations,
    mail,
    marketing,
    memory,
    notifications,
    onboarding,
    reminders,
    search,
    settings,
    support,
    todos,
    ui,
    voice,
    workflows,
)

CATALOG: Mapping[str, type[AnalyticsEvent]] = dict(sorted(registered_events().items()))

__all__ = ["CATALOG", "DOMAIN_MODULES"]
