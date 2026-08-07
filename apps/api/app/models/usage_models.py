from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import UserScopedDocument
from app.models.payment_models import PlanType


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


class RealtimeUsagePeriod(BaseModel):
    """Real-time usage counters for one feature/period window, read live from Redis."""

    used: int
    limit: int
    percentage: float
    reset_time: datetime
    remaining: int


class RealtimeFeatureUsage(BaseModel):
    """Real-time usage for one feature across its rate-limited periods."""

    title: str
    description: str
    periods: dict[str, RealtimeUsagePeriod] = Field(default_factory=dict)


class UsageSummaryResponse(BaseModel):
    """Response for ``GET /usage/summary``."""

    user_id: str
    plan_type: PlanType
    features: dict[str, RealtimeFeatureUsage]
    last_updated: datetime


class HistoryUsagePeriod(BaseModel):
    """Usage counters for one feature/period window in a stored usage snapshot."""

    used: int
    limit: int
    percentage: float


class HistoryFeatureUsage(BaseModel):
    """Snapshot usage for one feature across its rate-limited periods."""

    title: str
    periods: dict[str, HistoryUsagePeriod] = Field(default_factory=dict)


class UsageHistoryEntry(BaseModel):
    """One item in the ``GET /usage/history`` response list."""

    date: str
    plan_type: str
    features: dict[str, HistoryFeatureUsage]
