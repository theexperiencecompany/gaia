"""
Referral API request/response schemas.

Request and response contracts for the referral endpoints. Domain enums and
MongoDB document models live in ``app.models.referral_models``; these schemas are
the wire shapes the frontend consumes.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.referral_models import ReferralChannel, ReferralStatus

# ---------------------------------------------------------------------------
# Shared sub-shapes
# ---------------------------------------------------------------------------


class MilestoneState(BaseModel):
    """One step on the goal ladder, with its rendered state."""

    threshold: int = Field(description="Points required to unlock this milestone.")
    reward_months: int = Field(description="Free PRO months granted at this milestone.")
    cumulative_months: int = Field(description="Total free months earned through this milestone.")
    status: str = Field(description="One of 'done' | 'next' | 'locked'.")


class FriendReferral(BaseModel):
    """A referred friend as shown in the referrer's hub list."""

    display: str = Field(description="Friend's name or privacy-masked email.")
    status: ReferralStatus
    channel: ReferralChannel
    created_at: datetime
    upgraded_at: datetime | None = None


class EarnedReward(BaseModel):
    """A granted milestone reward (free months) and its redemption code."""

    months_granted: int
    milestone_threshold: int
    discount_code: str | None = None
    status: str = Field(description="One of 'granted' | 'reverted'.")
    granted_at: datetime


class ReferralStats(BaseModel):
    """Headline counters for the hub."""

    invited: int = Field(description="Friends invited (any channel).")
    joined: int = Field(description="Friends who signed up.")
    upgraded: int = Field(description="Friends who converted to PRO.")
    months_earned: int = Field(description="Total free PRO months earned.")


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class ReferralMeResponse(BaseModel):
    """Everything the referral hub + corner bar need for the current user."""

    code: str
    share_link: str
    points: int
    points_into_current_goal: int = Field(
        description="Points accumulated toward the next goal, from its lower bound."
    )
    next_goal_threshold: int = Field(description="Points needed to reach the next goal.")
    next_goal_reward_months: int = Field(description="Months unlocked by the next goal.")
    progress_pct: float = Field(description="Progress toward the next goal, 0-100.")
    ladder: list[MilestoneState]
    stats: ReferralStats
    friends: list[FriendReferral]
    rewards: list[EarnedReward]


class ResolveCodeResponse(BaseModel):
    """Public payload for the /invite/{code} landing page."""

    valid: bool
    referrer_name: str | None = None
    referrer_picture: str | None = None
    offer_label: str = Field(description="Human-readable friend offer, e.g. the $30 gift.")


class InviteResponse(BaseModel):
    """Outcome of sending email invites."""

    sent: list[str] = Field(description="Addresses an invite was sent to.")
    skipped: list[str] = Field(description="Addresses skipped (invalid/duplicate/existing user).")


class UpdateCodeResponse(BaseModel):
    """Result of changing the vanity code."""

    code: str
    share_link: str


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class InviteRequest(BaseModel):
    """Send referral invite emails to one or more friends."""

    emails: list[str] = Field(min_length=1, description="Friend email addresses to invite.")


class UpdateCodeRequest(BaseModel):
    """Set a custom vanity referral code."""

    code: str = Field(description="Desired vanity slug (validated server-side).")
