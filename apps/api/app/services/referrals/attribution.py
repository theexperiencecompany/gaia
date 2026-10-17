"""First-touch attribution: the invite link's cookie, carried through signup onto the new user.

The landing page resolves the code, which sets a 30-day first-party cookie
unless one is already there, so the first link clicked wins. Only a brand-new
account is attributed, and never to a referrer who is the same person.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.constants.referrals import (
    CODE_MAX_LENGTH,
    REFERRAL_COOKIE_VARIANT_SEPARATOR,
    ReferralCopyVariant,
    ReferralSource,
)
from app.db.repositories.referral_codes import referral_code_repository
from app.db.repositories.referrals import referral_repository
from app.db.repositories.users import user_repository
from app.models.referral_models import ReferralDocument
from app.services.analytics_service import capture
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

    def cookie_value(self) -> str:
        """Serialize as code[.variant[.source]]; a code never contains the separator."""
        parts = [self.code, self.landing_variant.value if self.landing_variant else ""]
        if self.source is not ReferralSource.INVITE_LINK:
            parts.append(self.source.value)
        return REFERRAL_COOKIE_VARIANT_SEPARATOR.join(parts).rstrip(
            REFERRAL_COOKIE_VARIANT_SEPARATOR
        )

    @classmethod
    def from_cookie(cls, raw: str | None) -> "ReferralAttribution | None":
        """Parse a cookie value; None for an absent or malformed one, which attributes nothing."""
        if not raw:
            return None
        code, _, rest = raw.partition(REFERRAL_COOKIE_VARIANT_SEPARATOR)
        variant, _, origin = rest.partition(REFERRAL_COOKIE_VARIANT_SEPARATOR)
        if not code or len(code) > CODE_MAX_LENGTH:
            return None
        variants = {member.value for member in ReferralCopyVariant}
        origins = {member.value for member in ReferralSource}
        return cls(
            code=code,
            landing_variant=ReferralCopyVariant(variant) if variant in variants else None,
            source=ReferralSource(origin) if origin in origins else ReferralSource.INVITE_LINK,
        )


def first_touch_cookie(
    existing: str | None, clicked: ReferralAttribution, *, valid: bool
) -> str | None:
    """Return the cookie value to set for a click, or None to leave the cookie alone.

    A valid code is written only when no live attribution is already there:
    the first link clicked keeps the friend for the whole window.
    """
    if not valid or ReferralAttribution.from_cookie(existing) is not None:
        return None
    return clicked.cookie_value()


async def attribute_signup(friend_user_id: str, attribution: ReferralAttribution) -> None:
    """Record who referred a user who just signed up; a self-referral or unknown code records nothing."""
    owner = await referral_code_repository.get_by_code(attribution.code)
    if owner is None:
        log.set_ns("referral", attribution="unknown_code")
        return
    friend = await user_repository.get(friend_user_id)
    referrer = await user_repository.get(owner.user_id)
    if friend is None or referrer is None:
        log.set_ns("referral", attribution="user_missing")
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
