"""Invite emails: from the referrer's Gmail when connected, else from GAIA's domain replying to them.

Every address is judged on its own. It is sent even when the recipient already
has an account, so the response never reveals who uses GAIA. A sender invites
a given friend once; an address that opted out is never mailed by anyone; and
a daily ceiling far above human use protects the sending domain.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import EmailStr, TypeAdapter, ValidationError

from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.referrals import (
    FRIEND_PRICE_LINE,
    INVITE_GMAIL_BODY,
    INVITE_NO_SENDER_EMAIL_MESSAGE,
    INVITE_NO_SENDER_EMAIL_WHY,
    INVITE_PRICE_LINE,
    INVITE_PROVIDER_REFUSED_WHY,
    INVITE_REGULAR_PRICE_LINE,
    INVITE_SEND_FAILED_FIX,
    INVITE_SEND_FAILED_MESSAGE,
    INVITE_SEND_FAILED_WHY,
    INVITE_SUBJECT_TEMPLATE,
)
from app.db.repositories.email_suppressions import email_suppression_repository
from app.db.repositories.referral_invites import referral_invite_repository
from app.models.referral_models import (
    ReferralInviteChannel,
    ReferralInviteDocument,
    ReferralInviteStatus,
    ReferralInviteSurface,
)
from app.models.user_models import UserDocument
from app.schemas.referrals import (
    ReferralInviteRequest,
    ReferralInviteResponse,
    ReferralInviteResult,
    ReferralOffer,
)
from app.services.analytics_service import capture
from app.services.email import ReferralInviteEmail, send_referral_invite_email
from app.services.mail.mail_service import EmailContent, send_email
from app.services.oauth.oauth_service import check_integration_status
from app.services.payments.payment_service import payment_service
from app.services.referrals.codes import ensure_code, first_name_of, load_user, share_link
from app.services.referrals.invite_quota import release_invites, reserve_invites
from app.services.referrals.offer import build_offer
from app.utils.email_utils import email_identity
from app.utils.errors import AppError
from app.utils.money import format_price
from app.utils.notification.unsubscribe import (
    UnsubscribeScope,
    build_invite_unsubscribe_url,
    verify_scoped_unsubscribe_token,
)
from shared.py.analytics import UserId
from shared.py.analytics.catalog.referrals import ReferralInviteSent
from shared.py.wide_events import log

_EMAIL = TypeAdapter(EmailStr)


def _valid_address(raw: str) -> str | None:
    try:
        return _EMAIL.validate_python(raw.strip()).lower()
    except ValidationError:
        return None


def invite_unsubscribe_subject(token: str) -> str | None:
    """Return the address an invite opt-out link was signed for, or None for a forged or foreign one."""
    return verify_scoped_unsubscribe_token(UnsubscribeScope.REFERRAL_INVITES, token)


async def unsubscribe_invite_recipient(token: str) -> bool:
    """Suppress every future invite to the link's address, whoever sends it; False for a bad token."""
    email = invite_unsubscribe_subject(token)
    if email is None:
        return False
    await email_suppression_repository.suppress(email)
    return True


def price_lines(offer: ReferralOffer) -> tuple[str, str]:
    """Return the intro price line and the regular price line, from the live offer."""
    return (
        INVITE_PRICE_LINE.format(
            intro=format_price(offer.monthly_intro_minor, offer.currency),
            cycles=offer.intro_cycles,
        ),
        INVITE_REGULAR_PRICE_LINE.format(
            regular=format_price(offer.monthly_regular_minor, offer.currency)
        ),
    )


def friend_price_line(offer: ReferralOffer) -> str:
    """Return the intro price as told to the referrer about a friend: $15/month for their first 2 months."""
    return FRIEND_PRICE_LINE.format(
        intro=format_price(offer.monthly_intro_minor, offer.currency), cycles=offer.intro_cycles
    )


@dataclass(frozen=True)
class _Batch:
    """What every invite in one request shares: who sends it, how, and with what gift."""

    sender: UserDocument
    sender_email: str
    surface: ReferralInviteSurface
    channel: ReferralInviteChannel
    link: str
    offer: ReferralOffer
    suppressed: frozenset[str]

    @property
    def sender_identity(self) -> str:
        return email_identity(self.sender_email)


async def _send(batch: _Batch, to: str) -> None:
    """Send one invite through the batch's mailbox; raises when it did not leave."""
    name = first_name_of(batch.sender) or batch.sender_email
    intro, regular = price_lines(batch.offer)
    unsubscribe_url = build_invite_unsubscribe_url(email_identity(to))
    if batch.channel is ReferralInviteChannel.GAIA:
        await send_referral_invite_email(
            ReferralInviteEmail(
                to=to,
                referrer_name=name,
                referrer_email=batch.sender_email,
                referrer_picture=batch.sender.picture,
                price_line=intro,
                regular_price_line=regular,
                invite_link=batch.link,
                unsubscribe_url=unsubscribe_url,
            )
        )
        return
    result = await send_email(
        batch.sender.id,
        to,
        EmailContent(
            subject=INVITE_SUBJECT_TEMPLATE.format(name=name),
            body=INVITE_GMAIL_BODY.format(
                price_line=intro, link=batch.link, name=name, unsubscribe_url=unsubscribe_url
            ),
        ),
    )
    if not result.successful:
        raise AppError(
            message=INVITE_SEND_FAILED_MESSAGE,
            why=INVITE_SEND_FAILED_WHY,
            fix=INVITE_SEND_FAILED_FIX,
            status_code=502,
            meta={"provider_error": result.error},
        )


async def _invite_one(batch: _Batch, address: str | None) -> ReferralInviteStatus:
    if address is None:
        return ReferralInviteStatus.INVALID
    identity = email_identity(address)
    if identity == batch.sender_identity:
        return ReferralInviteStatus.OWN_ADDRESS
    if identity in batch.suppressed:
        return ReferralInviteStatus.UNSUBSCRIBED
    claim = await referral_invite_repository.claim(
        ReferralInviteDocument(
            sender_user_id=batch.sender.id,
            recipient_email=identity,
            surface=batch.surface,
            channel=batch.channel,
            sent_at=datetime.now(UTC),
        )
    )
    if claim is None:
        return ReferralInviteStatus.ALREADY_INVITED
    try:
        await _send(batch, address)
    except AppError:
        await referral_invite_repository.release(claim.id)
        raise
    except Exception as e:
        await referral_invite_repository.release(claim.id)
        raise AppError(
            message=INVITE_SEND_FAILED_MESSAGE,
            why=INVITE_PROVIDER_REFUSED_WHY,
            status_code=502,
            meta={"channel": batch.channel.value, "error_type": type(e).__name__},
        ) from e
    capture(
        UserId(batch.sender.id),
        ReferralInviteSent(invite_surface=batch.surface.value, channel=batch.channel.value),
    )
    return ReferralInviteStatus.SENT


async def send_invites(user_id: str, request: ReferralInviteRequest) -> ReferralInviteResponse:
    """Judge and send each requested address, returning one result per address in request order."""
    sender = await load_user(user_id)
    if not sender.email:
        raise AppError(
            message=INVITE_NO_SENDER_EMAIL_MESSAGE,
            why=INVITE_NO_SENDER_EMAIL_WHY,
            status_code=409,
            meta={"user_id": user_id},
        )
    sender_identity = email_identity(sender.email)
    parsed = [(raw, _valid_address(raw)) for raw in request.emails]
    identities = [email_identity(address) for _, address in parsed if address]
    suppressed = frozenset(await email_suppression_repository.suppressed_among(identities))
    sendable = {
        identity
        for identity in identities
        if identity != sender_identity and identity not in suppressed
    }
    reservation = await reserve_invites(sender.id, len(sendable), datetime.now(UTC))
    results: list[ReferralInviteResult] = []
    try:
        gmail_connected = await check_integration_status(GMAIL_INTEGRATION_ID, sender.id)
        batch = _Batch(
            sender=sender,
            sender_email=sender.email,
            surface=request.surface,
            channel=ReferralInviteChannel.GMAIL if gmail_connected else ReferralInviteChannel.GAIA,
            link=share_link(await ensure_code(sender)),
            offer=build_offer(await payment_service.get_pro_plans()),
            suppressed=suppressed,
        )
        for raw, address in parsed:
            results.append(
                ReferralInviteResult(email=raw, status=await _invite_one(batch, address))
            )
    finally:
        await release_invites(
            reservation, sum(r.status is ReferralInviteStatus.SENT for r in results)
        )
    log.set_ns(
        "referral",
        invite_channel=batch.channel.value,
        invites_requested=len(results),
        invites_sent=sum(r.status is ReferralInviteStatus.SENT for r in results),
    )
    return ReferralInviteResponse(results=results)
