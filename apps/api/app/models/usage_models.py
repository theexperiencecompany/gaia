from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import UserScopedDocument


class UsagePeriod(str, Enum):
    DAY = "day"
    MONTH = "month"


class UsageInfo(BaseModel):
    """Usage information with limit and reset time."""

    used: int
    limit: int
    reset_time: datetime


class FeatureUsage(BaseModel):
    feature_key: str
    feature_title: str
    period: UsagePeriod
    used: int = 0
    limit: int = 0
    reset_time: datetime
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CreditUsage(BaseModel):
    """Tracks the monetary cost (credits) of usage."""

    credits_used: float = 0.0  # Total credits used (in USD)
    period: UsagePeriod = UsagePeriod.MONTH
    reset_time: datetime
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UserUsageSnapshot(UserScopedDocument):
    """A user's usage snapshot as stored in the ``usage_snapshots`` collection.

    User-scoped; ``id`` is the stringified Mongo ``_id``. ``created_at`` carries a
    90-day TTL (see indexes). Snapshots are hourly-aggregated: a write merges into
    the current hour's row and the base stamps ``updated_at``.
    """

    plan_type: str
    features: list[FeatureUsage] = Field(default_factory=list)
    credits: list[CreditUsage] = Field(default_factory=list)
    snapshot_date: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None


class UsageSnapshotUpdate(BaseModel):
    """Typed ``$set`` fields for a usage snapshot (the plan tier)."""

    model_config = ConfigDict(extra="forbid")

    plan_type: str | None = None
