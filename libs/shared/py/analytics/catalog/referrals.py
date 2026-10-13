"""Referral program events: invites sent, friends attributed and converting, months earned, nudges."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent
from shared.py.analytics.catalog.properties import Identifier, ObjectIdStr

__all__ = [
    "ReferralConverted",
    "ReferralInviteSent",
    "ReferralNudgeDismissed",
    "ReferralNudgeSent",
    "ReferralRewardGranted",
    "ReferralSignupAttributed",
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
