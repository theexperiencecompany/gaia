"""Request and response schemas of the /referrals routes; the web app builds against these names."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.constants.referrals import (
    INVITE_BATCH_MAX,
    ReferralCopyVariant,
    ReferralLayoutVariant,
)
from app.models.referral_models import (
    ReferralInviteStatus,
    ReferralInviteSurface,
    ReferralSuggestionReason,
    ReferredFriendStatus,
)
from app.schemas.common import ResponseModel
from app.schemas.usage import TimeSavedSummary


class ReferralOffer(ResponseModel):
    """The friend's gift in money, from the live Pro catalogue; amounts are in the currency's minor unit."""

    currency: str = Field(description="ISO 4217 code every amount below is in")
    monthly_regular_minor: int = Field(description="The monthly Pro price")
    monthly_intro_minor: int = Field(description="What a friend pays per month during the intro")
    intro_cycles: int = Field(description="How many monthly charges the intro price covers")
    yearly_regular_minor: int = Field(description="The yearly Pro price")
    yearly_discount_minor: int = Field(description="How much a friend saves on their first year")


class ReferredFriend(ResponseModel):
    first_name: str | None = Field(
        description="The friend's first name, when their account has one"
    )
    status: ReferredFriendStatus
    joined_at: datetime
    paid_at: datetime | None = Field(
        default=None, description="When their first payment went through"
    )


class ReferralMeResponse(ResponseModel):
    """The caller's referral link, gift, progress and friends, plus the experiment's variants."""

    code: str
    share_link: str
    offer: ReferralOffer
    months_earned: int = Field(description="Free months earned in total, applied or banked")
    months_applied: int = Field(description="Free months already added to the billing date")
    months_banked: int = Field(description="Free months waiting for an active subscription")
    next_billing_date: datetime | None = Field(
        default=None, description="The caller's next charge, after any free months"
    )
    friends: list[ReferredFriend] = Field(
        description="Everyone who joined through the link, newest first"
    )
    copy_variant: ReferralCopyVariant
    layout_variant: ReferralLayoutVariant


class ReferralResolveResponse(ResponseModel):
    """What an invite landing page shows; valid is false for a code nobody owns."""

    valid: bool
    referrer_first_name: str | None = None
    referrer_picture: str | None = None
    offer: ReferralOffer


class ReferralSuggestion(ResponseModel):
    name: str | None = Field(default=None, description="Display name, when the source carried one")
    email: str
    reason: ReferralSuggestionReason
    count: int = Field(description="Meetings shared or emails sent in the lookback window")


class ReferralSuggestionsResponse(ResponseModel):
    suggestions: list[ReferralSuggestion] = Field(description="Ranked by how often you interact")


class ReferralInviteRequest(BaseModel):
    """A batch of addresses to invite; each is judged on its own, so one invalid address fails nothing."""

    emails: list[str] = Field(min_length=1, max_length=INVITE_BATCH_MAX)
    surface: ReferralInviteSurface


class ReferralInviteResult(ResponseModel):
    email: str = Field(description="The address exactly as it was sent in the request")
    status: ReferralInviteStatus


class ReferralInviteResponse(ResponseModel):
    results: list[ReferralInviteResult] = Field(
        description="One result per requested address, in order"
    )


class ReferralWorkflowCreditResponse(ResponseModel):
    """Whether pressing Use on a community workflow credited its creator for the visitor's signup."""

    credited: bool = Field(
        description="False when the creator can't refer anyone or an earlier link already won"
    )


class ReferralWeeklyCardResponse(ResponseModel):
    """The Monday recap card: last week's time saved, and the link to share it with."""

    show: bool = Field(description="Whether chat surfaces the card today")
    stats: TimeSavedSummary
    code: str
    share_link: str
    copy_variant: ReferralCopyVariant


class ReferralChatCardResponse(ResponseModel):
    """Whether the chat may show its share card now; a true answer spends this week's nudge."""

    show: bool


class ReferralNudgeDismissResponse(ResponseModel):
    paused: bool = Field(description="This dismissal paused every referral nudge for 30 days")
