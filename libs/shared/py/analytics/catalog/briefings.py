"""Daily brief and weekly recap events."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent
from shared.py.analytics.catalog.properties import Identifier

__all__ = [
    "BriefingDayZeroHelloSent",
    "BriefingKindName",
    "BriefingOpened",
    "BriefingPostmarksViewed",
    "BriefingProvisioned",
    "BriefingSent",
]

BriefingKindName = Literal["daily", "weekly"]


class BriefingSent(ServerEvent):
    """A brief was stored and delivered; which edition it was drawn in and where it went."""

    event: ClassVar[str] = "briefing:sent"
    budget_per_user_day: ClassVar[int] = 4

    kind: BriefingKindName
    family: Identifier
    mood: Identifier
    item_count: int
    channel_count: int


class BriefingOpened(ServerEvent):
    """A user opened one of their briefs on its own page for the first time."""

    event: ClassVar[str] = "briefing:opened"
    budget_per_user_day: ClassVar[int] = 4

    kind: BriefingKindName


class BriefingPostmarksViewed(ServerEvent):
    """A user opened Postmarks, the collection of Air Mail city stamps from their briefs."""

    event: ClassVar[str] = "briefing:postmarks_viewed"
    budget_per_user_day: ClassVar[int] = 20

    collected: int
    total: int


class BriefingProvisioned(ServerEvent):
    """The daily brief and weekly recap schedules were created for a user."""

    event: ClassVar[str] = "briefing:provisioned"
    budget_per_user_day: ClassVar[int] = 2

    held_for_goal: bool


class BriefingDayZeroHelloSent(ServerEvent):
    """GAIA's first text reached a freshly linked chat platform."""

    event: ClassVar[str] = "briefing:day_zero_hello_sent"
    budget_per_user_day: ClassVar[int] = 2

    platform: Identifier
    has_goal: bool
