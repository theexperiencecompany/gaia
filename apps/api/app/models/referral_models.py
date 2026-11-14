"""Referral program enums and the documents of its five collections."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.constants.referrals import ReferralCopyVariant, ReferralNudge
from app.db.repositories.base import MongoDocument
from app.models.payment_models import PlanDuration


class ReferredFriendStatus(StrEnum):
    """Where a referred friend is: signed up, or past their first successful payment."""

    JOINED = "joined"
    PAID = "paid"


class ReferredFriendStanding(StrEnum):
    """How the referral page lists a friend: joined, paid, or refunded, a first payment taken back."""

    JOINED = "joined"
    PAID = "paid"
    REFUNDED = "refunded"


class ReferralRewardState(StrEnum):
    """What became of the free month a paying friend earned their referrer.

    PENDING is claimed but not yet delivered; APPLIED moved the referrer's Dodo
    billing date; BANKED waits for a referrer with no active subscription to
    come back; SELF_REFERRAL earned nothing because both sides are one person;
    REVOKED was taken back because the friend's first payment was refunded or disputed.
    """

    PENDING = "pending"
    APPLIED = "applied"
    BANKED = "banked"
    SELF_REFERRAL = "self_referral"
    REVOKED = "revoked"


class ReferralRevokeReason(StrEnum):
    """Why a friend's first payment stopped counting: Dodo refunded it, or the payer disputed it."""

    REFUND = "refund"
    DISPUTE = "dispute"


class ReferralInviteSurface(StrEnum):
    """Where in the product an invite was sent from."""

    PAGE = "page"
    HOVER_CARD = "hover_card"
    AGENT = "agent"
    SUGGESTION = "suggestion"


class ReferralInviteStatus(StrEnum):
    """The outcome of one address in an invite batch."""

    SENT = "sent"
    ALREADY_INVITED = "already_invited"
    INVALID = "invalid"
    UNSUBSCRIBED = "unsubscribed"
    OWN_ADDRESS = "own_address"


class ReferralInviteChannel(StrEnum):
    """Which mailbox an invite left from."""

    GMAIL = "gmail"
    GAIA = "gaia"


class ReferralSuggestionReason(StrEnum):
    """Why a contact is suggested: met in meetings, or emailed."""

    MET = "met"
    EMAILED = "emailed"


class ReferralCodeDocument(MongoDocument):
    """A Pro user's referral code; one per user, never edited."""

    user_id: str
    code: str
    created_at: datetime


class ReferralDocument(MongoDocument):
    """One referred friend: who referred them, and how far they and the reward have got."""

    friend_user_id: str
    referrer_user_id: str
    code: str
    landing_variant: ReferralCopyVariant | None = None
    status: ReferredFriendStatus = ReferredFriendStatus.JOINED
    joined_at: datetime
    paid_at: datetime | None = None
    payment_id: str | None = None
    gift_codes: dict[PlanDuration, str] = Field(default_factory=dict)
    reward_state: ReferralRewardState | None = None
    reward_subscription_id: str | None = None
    reward_target_billing_date: datetime | None = None
    reward_applied_at: datetime | None = None
    revoke_reason: ReferralRevokeReason | None = None
    revoked_at: datetime | None = None
    revoke_target_billing_date: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @property
    def refunded(self) -> bool:
        """Whether the friend's first payment was refunded or disputed, so it earns nothing."""
        return self.revoke_reason is not None

    @property
    def revocation_owed(self) -> bool:
        """Whether a refund or dispute asked for this reward back and it is not yet taken."""
        return self.refunded and self.reward_state is not ReferralRewardState.REVOKED


class ReferralUpdate(BaseModel):
    """The reward fields a referral advances through once its friend has paid."""

    model_config = ConfigDict(extra="forbid")

    reward_state: ReferralRewardState | None = None
    reward_subscription_id: str | None = None
    reward_target_billing_date: datetime | None = None
    reward_applied_at: datetime | None = None
    revoke_target_billing_date: datetime | None = None


class ReferralInviteDocument(MongoDocument):
    """One invite email; the (sender, recipient) pair is unique, so a friend is invited once."""

    sender_user_id: str
    recipient_email: str
    surface: ReferralInviteSurface
    channel: ReferralInviteChannel
    sent_at: datetime


class EmailSuppressionDocument(MongoDocument):
    """An address that opted out of every invite GAIA sends, whoever the sender."""

    email: str
    created_at: datetime


class ReferralNudgeStateDocument(MongoDocument):
    """One user's nudge budget: when GAIA last messaged them about sharing, and their dismissals."""

    user_id: str
    last_nudged_at: datetime | None = None
    sent_at: dict[ReferralNudge, datetime] = Field(default_factory=dict)
    dismissals: int = 0
    paused_until: datetime | None = None
