"""Referral program events: invites, attribution, conversions, months earned and nudges; plus the UI-only taps."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier, ObjectIdStr

__all__ = [
    "GiftMintFailureReason",
    "ReferralBankedMonthApplied",
    "ReferralCardDismissed",
    "ReferralConverted",
    "ReferralGiftCheckoutOpened",
    "ReferralGiftMintFailed",
    "ReferralInviteSent",
    "ReferralInviteUndone",
    "ReferralLandingOutcome",
    "ReferralLandingResolved",
    "ReferralNudgeDismissed",
    "ReferralNudgeSent",
    "ReferralRewardGranted",
    "ReferralRewardRevoked",
    "ReferralSentWithGaiaAppended",
    "ReferralShareClicked",
    "ReferralSignupAttributed",
    "RevokeReason",
]

ReferralLandingOutcome = Literal["valid", "disabled"]
RevokeReason = Literal["refund", "dispute"]
GiftMintFailureReason = Literal[
    "provider_unreachable", "provider_rejected", "provider_invalid_response"
]


class ReferralInviteSent(ServerEvent):
    """A referrer's invite email left, from their Gmail or GAIA's domain; one per recipient."""

    event: ClassVar[str] = "referral:invite_sent"
    # Above the server's daily send ceiling, so the ceiling trips first.
    budget_per_user_day: ClassVar[int] = 250

    invite_surface: Identifier
    channel: Identifier


class ReferralSignupAttributed(ServerEvent):
    """A new user signed up through a referral link; captured on the friend."""

    event: ClassVar[str] = "referral:signup_attributed"
    budget_per_user_day: ClassVar[int] = 5

    referrer_id: ObjectIdStr
    landing_variant: Identifier | None = None
    # What brought them: someone's invite link, or a creator's public workflow.
    source: Literal["invite_link", "workflow"]


class ReferralConverted(ServerEvent):
    """A referred friend's first payment succeeded; captured on the friend."""

    event: ClassVar[str] = "referral:converted"
    budget_per_user_day: ClassVar[int] = 5

    referrer_id: ObjectIdStr
    landing_variant: Identifier | None = None
    self_referral: bool


class ReferralRewardGranted(ServerEvent):
    """A referrer earned a free month for a paying friend; captured on the referrer."""

    event: ClassVar[str] = "referral:reward_granted"
    budget_per_user_day: ClassVar[int] = 50

    friend_id: ObjectIdStr
    delivery: Identifier
    months: int


class ReferralSentWithGaiaAppended(ServerEvent):
    """GAIA added the opt-in "Sent with GAIA" invite line to an email it wrote for the user."""

    event: ClassVar[str] = "referral:sent_with_gaia_appended"
    budget_per_user_day: ClassVar[int] = 250

    tool: Identifier


class ReferralNudgeSent(ServerEvent):
    """GAIA messaged the user about sharing on its own: a pitch under the weekly cap, or a reward note."""

    event: ClassVar[str] = "referral:nudge_sent"
    # One pitch a week plus a reward note per paying friend.
    budget_per_user_day: ClassVar[int] = 50

    nudge: Identifier


class ReferralNudgeDismissed(ServerEvent):
    """The user dismissed a referral nudge; the dismissal that pauses nudges says so."""

    event: ClassVar[str] = "referral:nudge_dismissed"
    budget_per_user_day: ClassVar[int] = 10

    nudge: Identifier
    paused: bool


ReferralCopyVariantName = Literal["gift", "earn", "time_back"]


class ReferralShareClicked(WebEvent):
    """The user picked a way to share their invite link: the native sheet, a channel, copy or QR."""

    event: ClassVar[str] = "referral:share_clicked"
    budget_per_user_day: ClassVar[int] = 50

    surface: Literal["page", "sidebar", "post_payment", "chat_card", "weekly_stats"]
    channel: Literal["native", "whatsapp", "sms", "x", "linkedin", "email", "copy", "qr"]
    copy_variant: ReferralCopyVariantName


class ReferralCardDismissed(WebEvent):
    """The user closed a referral prompt without sharing."""

    event: ClassVar[str] = "referral:card_dismissed"
    budget_per_user_day: ClassVar[int] = 10

    surface: Literal["sidebar", "post_payment"]
    copy_variant: ReferralCopyVariantName


class ReferralInviteUndone(WebEvent):
    """The user took back an email invite inside the undo window, before it was sent."""

    event: ClassVar[str] = "referral:invite_undone"
    budget_per_user_day: ClassVar[int] = 50

    surface: Literal["hover_card", "page", "suggestion"]


class ReferralLandingResolved(ServerEvent):
    """Someone opened a referrer's invite link; captured on the referrer, since the visitor has no account."""

    event: ClassVar[str] = "referral:landing_resolved"
    budget_per_user_day: ClassVar[int] = 500

    outcome: ReferralLandingOutcome
    landing_variant: Identifier | None = None
    cookie_set: bool


class ReferralGiftCheckoutOpened(ServerEvent):
    """A referred friend's checkout opened with their gift code applied; captured on the friend."""

    event: ClassVar[str] = "referral:gift_checkout_opened"
    budget_per_user_day: ClassVar[int] = 20

    referrer_id: ObjectIdStr
    duration: Identifier


class ReferralGiftMintFailed(ServerEvent):
    """Dodo could not mint a referred friend's gift, so their checkout opened without it."""

    event: ClassVar[str] = "referral:gift_mint_failed"
    budget_per_user_day: ClassVar[int] = 20

    reason: GiftMintFailureReason


class ReferralRewardRevoked(ServerEvent):
    """A paying friend's first payment was refunded or disputed, so their referrer's month was taken back.

    reclaimed is false when the month was already under way and could not be moved back.
    """

    event: ClassVar[str] = "referral:reward_revoked"
    budget_per_user_day: ClassVar[int] = 50

    friend_id: ObjectIdStr
    reason: RevokeReason
    prior_state: Identifier
    reclaimed: bool


class ReferralBankedMonthApplied(ServerEvent):
    """A free month the referrer banked while unsubscribed moved their billing date; one per friend."""

    event: ClassVar[str] = "referral:banked_month_applied"
    budget_per_user_day: ClassVar[int] = 50

    friend_id: ObjectIdStr
    months: int
