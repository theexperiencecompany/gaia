"""Response schemas for the usage endpoints.

The wire contract these describe is mirrored in TypeScript at
``libs/shared/ts/src/types/usage.ts`` (``UsageSummary`` and friends) — change
both together.
"""

from pydantic import BaseModel, Field


class FeaturePeriodUsage(BaseModel):
    """One feature's usage within one window (day or month)."""

    used: int
    limit: int
    percentage: float
    reset_time: str
    remaining: int


class FeatureUpgrade(BaseModel):
    """The Pro tier's limits for a feature, so a free user sees the delta."""

    day: int
    month: int


class FeatureUsageSummary(BaseModel):
    title: str
    description: str
    upgrade: FeatureUpgrade
    # Only windows with a limit configured for the user's plan are present.
    periods: dict[str, FeaturePeriodUsage] = Field(default_factory=dict)


class BudgetWindow(BaseModel):
    """One cost-budget window: how much of the allowance is used, and when it
    resets. Deliberately no raw USD — see ``cost_budget.get_budget_status``."""

    percentage: float
    reset_time: str


class UsageBudget(BaseModel):
    daily: BudgetWindow
    # Free has no monthly cost budget, so this is null there.
    monthly: BudgetWindow | None = None
    per_request_token_ceiling: int


class UsageSummary(BaseModel):
    user_id: str
    plan_type: str
    # The feature the usage UI leads with, owned by the API so the client never
    # hard-codes it (see ``PRIMARY_METERED_FEATURE``).
    primary_feature: str
    features: dict[str, FeatureUsageSummary]
    budget: UsageBudget
    last_updated: str
