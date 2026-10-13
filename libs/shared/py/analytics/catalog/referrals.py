"""Referral program events: invites sent, friends attributed and converting, months earned."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent
from shared.py.analytics.catalog.properties import Identifier, ObjectIdStr

__all__ = [
    "ReferralConverted",
    "ReferralInviteSent",
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
