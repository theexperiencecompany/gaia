"""
Referral domain models.

MongoDB document models for the referral program: the per-friend ``referrals``
record and the ``referral_rewards`` ledger. Enums capture the lifecycle of a
referral and the state of a granted reward.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ReferralStatus(str, Enum):
    """Lifecycle of a single referred friend.

    Progression is monotonic up to ``UPGRADED``/``RENEWED``; ``REVERTED`` is a
    terminal state reached only via refund/chargeback clawback.
    """

    INVITED = "invited"  # An email invite was sent; friend has not signed up yet.
    SIGNED_UP = "signed_up"  # Friend created an account via the referrer's link.
    ACTIVATED = "activated"  # Friend reached the real-usage activation threshold.
    UPGRADED = "upgraded"  # Friend subscribed to PRO (the revenue event).
    RENEWED = "renewed"  # Friend's subscription survived its first renewal.
    REVERTED = "reverted"  # Friend's payment was refunded/charged back in window.


class ReferralChannel(str, Enum):
    """How the referral was initiated."""

    LINK = "link"
    EMAIL = "email"
    GOOGLE_IMPORT = "google_import"
    SOCIAL = "social"


class ReferralRewardStatus(str, Enum):
    """State of a milestone reward in the ledger."""

    GRANTED = "granted"
    REVERTED = "reverted"


class ReferralModel(BaseModel):
    """A single referred friend, owned by the referrer.

    One document per (referrer, friend). ``referred_user_id`` is set once the
    friend signs up; ``referred_email`` is populated for email invites that have
    not yet converted to an account.
    """

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    referrer_user_id: str = Field(description="User id of the referrer who owns this referral.")
    referred_user_id: str | None = Field(
        default=None, description="User id of the referred friend, once they sign up."
    )
    referred_email: str | None = Field(
        default=None, description="Invitee email for email invites not yet signed up."
    )
    status: ReferralStatus = Field(default=ReferralStatus.INVITED)
    channel: ReferralChannel = Field(default=ReferralChannel.LINK)
    points_awarded: int = Field(
        default=0, description="Points this referral has contributed to the referrer."
    )
    friend_discount_code: str | None = Field(
        default=None, description="Unique Dodo discount code minted for the friend's checkout."
    )
    invited_at: datetime | None = None
    clicked_at: datetime | None = None
    signed_up_at: datetime | None = None
    activated_at: datetime | None = None
    upgraded_at: datetime | None = None
    renewed_at: datetime | None = None
    reverted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ReferralRewardModel(BaseModel):
    """A milestone reward granted to a referrer.

    Uniqueness on ``(referrer_user_id, milestone_threshold)`` makes reward grants
    idempotent under webhook retries and is the anchor for clawbacks.
    """

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    referrer_user_id: str
    milestone_threshold: int = Field(
        description="Points threshold of the milestone (its stable identifier)."
    )
    months_granted: int = Field(description="Free PRO months unlocked at this milestone.")
    dodo_discount_code: str | None = Field(
        default=None, description="100%-off Dodo code minted as the redemption vehicle."
    )
    dodo_discount_id: str | None = Field(default=None)
    status: ReferralRewardStatus = Field(default=ReferralRewardStatus.GRANTED)
    granted_at: datetime
    reverted_at: datetime | None = None
