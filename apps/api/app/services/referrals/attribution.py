"""First-touch attribution: the invite link's cookie, carried through signup onto the new user.

The landing page resolves the code, which sets a 30-day first-party cookie
unless one is already there, so the first link clicked wins. Only a brand-new
account is attributed, and never to a referrer who is the same person.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
import re

from app.constants.referrals import (
    CODE_MAX_LENGTH,
    REFERRAL_COOKIE_VARIANT_SEPARATOR,
    WORKFLOW_ID_PATTERN,
    ReferralCopyVariant,
    ReferralSource,
)
from app.db.repositories.referral_codes import referral_code_repository
from app.db.repositories.referrals import referral_repository
from app.db.repositories.users import user_repository
from app.models.referral_models import ReferralDocument
from app.services.analytics_service import capture
from app.services.referrals.availability import referrals_enabled
from app.utils.email_utils import email_identity
from app.utils.timezone import as_utc
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.referrals import ReferralSignupAttributed
from shared.py.wide_events import log


@dataclass(frozen=True)
class ReferralAttribution:
    """What the attribution cookie carries: the code, the landing copy shown, and what brought the friend."""

    code: str
    landing_variant: ReferralCopyVariant | None = None
    source: ReferralSource = ReferralSource.INVITE_LINK
    workflow_id: str | None = None

    def cookie_value(self) -> str:
        """Serialize as code[.variant[.source[.workflow]]]; no part contains the separator."""
        parts = [self.code, self.landing_variant.value if self.landing_variant else ""]
        if self.source is not ReferralSource.INVITE_LINK:
            parts.append(self.source.value)
            if self.workflow_id:
                parts.append(self.workflow_id)
        return REFERRAL_COOKIE_VARIANT_SEPARATOR.join(parts).rstrip(
            REFERRAL_COOKIE_VARIANT_SEPARATOR
        )

    @classmethod
    def from_cookie(cls, raw: str | None) -> "ReferralAttribution | None":
        """Parse a cookie value; None for an absent or malformed one, which attributes nothing."""
        if not raw:
            return None
        code, _, rest = raw.partition(REFERRAL_COOKIE_VARIANT_SEPARATOR)
        variant, _, rest = rest.partition(REFERRAL_COOKIE_VARIANT_SEPARATOR)
        origin, _, workflow_id = rest.partition(REFERRAL_COOKIE_VARIANT_SEPARATOR)
        if not code or len(code) > CODE_MAX_LENGTH:
            return None
        variants = {member.value for member in ReferralCopyVariant}
        origins = {member.value for member in ReferralSource}
        source = ReferralSource(origin) if origin in origins else ReferralSource.INVITE_LINK
        return cls(
            code=code,
            landing_variant=ReferralCopyVariant(variant) if variant in variants else None,
            source=source,
            workflow_id=workflow_id
            if source is ReferralSource.WORKFLOW and re.fullmatch(WORKFLOW_ID_PATTERN, workflow_id)
            else None,
        )


def first_touch_cookie(
    existing: str | None, clicked: ReferralAttribution, *, valid: bool
) -> str | None:
    """Return the cookie value to set for a click, or None to leave the cookie alone.

    The first link clicked keeps the friend for the whole window, with one
    exception: a friend's own invite link always replaces credit a workflow's
    creator was holding, and a workflow never replaces an invite.
    """
    if not valid:
        return None
    held = ReferralAttribution.from_cookie(existing)
    if held is None or (
        held.source is ReferralSource.WORKFLOW and clicked.source is ReferralSource.INVITE_LINK
    ):
        return clicked.cookie_value()
    return None


async def attribute_signup(friend_user_id: str, attribution: ReferralAttribution) -> None:
    """Record who referred a user who just signed up; a self-referral, unknown code or switched-off program records nothing."""
    owner = await referral_code_repository.get_by_code(attribution.code)
    if owner is None:
        log.set_ns("referral", attribution="unknown_code")
        return
    friend = await user_repository.get(friend_user_id)
    referrer = await user_repository.get(owner.user_id)
    if friend is None or referrer is None:
        log.set_ns("referral", attribution="user_missing")
        return
    # An old link's cookie outlives a switch-off; the program starts no new friendships while off.
    if not await referrals_enabled(referrer.id):
        log.set_ns("referral", attribution="referrals_off")
        return
    if friend.id == referrer.id or (
        friend.email
        and referrer.email
        and email_identity(friend.email) == email_identity(referrer.email)
    ):
        log.set_ns("referral", attribution="self_referral")
        return

    now = datetime.now(UTC)
    created = await referral_repository.attribute(
        ReferralDocument(
            friend_user_id=friend.id,
            referrer_user_id=referrer.id,
            code=attribution.code,
            landing_variant=attribution.landing_variant,
            source=attribution.source,
            workflow_id=attribution.workflow_id,
            joined_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    if created is None:
        log.set_ns("referral", attribution="already_referred")
        return
    log.set_ns("referral", attribution="attributed", referrer_id=referrer.id)
    capture(
        UserId(friend.id),
        ReferralSignupAttributed(
            referrer_id=referrer.id,
            landing_variant=attribution.landing_variant.value
            if attribution.landing_variant
            else None,
            source=attribution.source.value,
        ),
        dedupe=Dedupe(key=friend.id, occurred_at=as_utc(created.joined_at) or now),
    )
