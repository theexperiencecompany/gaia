"""Referral program events: the UI-only moments the server never sees."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import WebEvent

__all__ = [
    "ReferralCardDismissed",
    "ReferralInviteUndone",
    "ReferralShareClicked",
]

ReferralCopyVariantName = Literal["gift", "earn", "time_back", "insider"]


class ReferralShareClicked(WebEvent):
    """The user picked a way to share their invite link: the native sheet, a channel, copy or QR."""

    event: ClassVar[str] = "referral:share_clicked"
    budget_per_user_day: ClassVar[int] = 50

    surface: Literal["page", "sidebar", "post_payment"]
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
