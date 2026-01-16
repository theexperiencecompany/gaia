from datetime import datetime, timezone
from enum import Enum
from typing import List

from pydantic import BaseModel, Field


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
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CreditUsage(BaseModel):
    """Tracks the monetary cost (credits) of usage."""

    credits_used: float = 0.0  # Total credits used (in USD)
    period: UsagePeriod = UsagePeriod.MONTH
    reset_time: datetime
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserUsageSnapshot(BaseModel):
    user_id: str
    plan_type: str
    features: List[FeatureUsage] = []
    credits: List[CreditUsage] = []  # Field for tracking credits
    snapshot_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
