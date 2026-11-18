"""One user's briefing state: their schedule and editions, and what the brief engine keeps between runs."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.constants.briefing import BriefingBag, EditionChoice
from app.db.repositories.base import MongoDocument
from app.models.brief_settings_models import BriefingSchedule


class BriefingBootstrap(BaseModel):
    """An existing user's briefs held until a goal is known (see briefing.rollout)."""

    pending: bool
    since: datetime


class BriefingDormancy(BaseModel):
    """The idle ladder: consecutive idle days, the last day counted, when the brief
    went dormant (None while it is still running), and when it last asked about a goal."""

    idle_days: int = Field(default=0, ge=0)
    date: str | None = None
    dormant_since: datetime | None = None
    #: When a brief last asked whether the user's remembered goal is still live.
    goal_asked_at: datetime | None = None


class DayZeroHello(BaseModel):
    """When and where GAIA's first text after a platform link went out."""

    sent_at: datetime
    platform: str


class ShuffleBag(BaseModel):
    """One pass of a per-user shuffle bag (``app/services/briefing/shuffle_bag.py``):
    the pass's order and how many of it have been drawn."""

    order: list[str]
    index: int = Field(ge=0)


class BagDraw(BaseModel):
    """Today's member of one shuffle bag and the state that continues its pass."""

    model_config = ConfigDict(frozen=True)

    bag: BriefingBag
    member: str
    next_state: ShuffleBag


class BriefingStateDocument(MongoDocument):
    """A user's briefing state as stored in briefing_state; a user with no row has every default.

    editions is keyed by family name, not EditionFamily: a stored family may since have
    been retired, and its row must still read.
    """

    user_id: str
    schedule: BriefingSchedule = Field(default_factory=BriefingSchedule)
    #: Daily edition families taken out of the rotation or favourited; an absent family is on.
    editions: dict[str, EditionChoice] = Field(default_factory=dict)
    bootstrap: BriefingBootstrap | None = None
    dormancy: BriefingDormancy | None = None
    day_zero_hello: DayZeroHello | None = None
    shuffle_bags: dict[BriefingBag, ShuffleBag] = Field(default_factory=dict)


class BriefingStateUpdate(BaseModel):
    """The settings a user replaces whole; the engine's own state has named writers."""

    model_config = ConfigDict(extra="forbid")

    schedule: BriefingSchedule | None = None
    editions: dict[str, EditionChoice] | None = None
