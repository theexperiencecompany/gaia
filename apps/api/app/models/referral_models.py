"""Referral program enums and the documents of its four collections."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.constants.referrals import ReferralCopyVariant
from app.db.repositories.base import MongoDocument
from app.models.payment_models import PlanDuration


class ReferredFriendStatus(StrEnum):
    """Where a referred friend is: signed up, or past their first successful payment."""

    JOINED = "joined"
    PAID = "paid"


class ReferralRewardState(StrEnum):
    """What became of the free month a paying friend earned their referrer.

    PENDING is claimed but not yet delivered; APPLIED moved the referrer's Dodo
    billing date; BANKED waits for a referrer with no active subscription to
    come back; SELF_REFERRAL earned nothing because both sides are one person.
    """

    PENDING = "pending"
    APPLIED = "applied"
    BANKED = "banked"
    SELF_REFERRAL = "self_referral"


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
    reward_target_billing_date: datetime | None = None
    reward_applied_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ReferralUpdate(BaseModel):
    """The reward fields a referral advances through once its friend has paid."""

    model_config = ConfigDict(extra="forbid")

    reward_state: ReferralRewardState | None = None
    reward_target_billing_date: datetime | None = None
    reward_applied_at: datetime | None = None


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
