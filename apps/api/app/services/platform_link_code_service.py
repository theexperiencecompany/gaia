"""One-tap platform-linking codes, minted by the web during onboarding.

The mirror image of platform_link_token (endpoints/bot.py), which the
BOT mints and the WEB redeems: here the WEB mints a code bound to the user, the
user carries it to the platform (invisibly in a Telegram deep link, visibly as a
trailing #code in the WhatsApp/iMessage message they send), and the BOT
redeems it on first contact. Nobody has to type /auth.

Security properties match connect_link_service (128-bit opaque code, the
binding lives server-side, bounded TTL) except for how the code is spent: a
redemption takes a short-lived claim (claim_platform_link_code) and deletes the
record once the link is written (discard_platform_link_code). A redemption
refused before the link is written releases the claim (release_platform_link_code)
so the retry can use the same code; one that breaks after spends it, because a
retry would run the existing link's side effects a second time.
"""

import secrets
from urllib.parse import quote

from pydantic import BaseModel
from redis.exceptions import RedisError

from app.config.settings import settings
from app.constants.auth import PLATFORM_LINK_CODE_BYTES
from app.constants.cache import (
    PLATFORM_LINK_CODE_CLAIM_ATTEMPTS,
    PLATFORM_LINK_CODE_CLAIM_HELD,
    PLATFORM_LINK_CODE_CLAIM_SPENT,
    PLATFORM_LINK_CODE_CLAIM_TTL,
    PLATFORM_LINK_CODE_PREFIX,
    PLATFORM_LINK_CODE_TTL,
)
from app.db.redis import delete_cache, get_cache, redis_cache, set_cache
from app.models.user_models import OnboardingPreferences
from app.services.platform_link_service import Platform
from app.utils.errors import create_error
from shared.py.wide_events import log


class PlatformLinkCodePayload(BaseModel):
    """What a live link code resolves to.

    The onboarding answers travel with the code rather than a pre-rendered
    string: the bot's first contact is composed at REDEEM time, when the user's
    connected integrations are known, and rendering it at mint time would have
    frozen a set of connect links minutes before they were sent.
    """

    user_id: str
    preferences: OnboardingPreferences


class LinkCodeClaim(BaseModel):
    """What trying to take a code found.

    ``payload`` is set only for the caller that won the claim. ``in_flight``
    marks the one that lost it to a twin redemption still running — a distinct
    state from a code that is simply gone, because the two owe the presenting
    account opposite answers.
    """

    payload: PlatformLinkCodePayload | None = None
    in_flight: bool = False


def _code_key(code: str) -> str:
    return f"{PLATFORM_LINK_CODE_PREFIX}:{code}"


def _claim_key(code: str) -> str:
    return f"{PLATFORM_LINK_CODE_PREFIX}:claim:{code}"


def build_handoff_text(first_message: str, code: str) -> str:
    """Build the exact text a WhatsApp/iMessage user sends: the message plus its code.

    The adapters strip the #<code> suffix back off before the text reaches
    the agent, so the trailing separator here is part of the wire format.
    """
    return f"{first_message} #{code}"


def build_handoff_links(code: str, first_message: str) -> dict[str, str]:
    """Deep links that carry code to each platform the onboarding offers.

    iMessage is absent by construction: its number is assigned per user out of
    Photon's shared pool by start_platform_connect, so no link exists until
    the user has registered a phone. The client builds that one from
    handoff_text and the contact_number that call returns.
    """
    handoff = quote(build_handoff_text(first_message, code))
    links: dict[str, str] = {}

    if settings.TELEGRAM_BOT_USERNAME:
        links[Platform.TELEGRAM.value] = (
            f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={code}"
        )
    if settings.WHATSAPP_PHONE_NUMBER:
        links[Platform.WHATSAPP.value] = (
            f"https://wa.me/{settings.WHATSAPP_PHONE_NUMBER}?text={handoff}"
        )
    return links


async def mint_platform_link_code(user_id: str, preferences: OnboardingPreferences) -> str:
    """Bind a fresh single-use code to user_id and their onboarding answers."""
    code = secrets.token_urlsafe(PLATFORM_LINK_CODE_BYTES)
    stored = await set_cache(
        _code_key(code),
        PlatformLinkCodePayload(user_id=user_id, preferences=preferences).model_dump(mode="json"),
        ttl=PLATFORM_LINK_CODE_TTL,
    )
    if not stored:
        # Handing out a code nothing can resolve would strand the user on a bot
        # that says "expired" the moment they arrive.
        log.error(
            "could not store the one-tap link code",
            user={"id": user_id},
            operation="mint_platform_link_code",
        )
        raise create_error(
            message="Could not start platform linking. Please retry.",
            why="the link code could not be stored (Redis unavailable)",
            fix="retry in a moment, or connect the platform from settings with /auth",
            status_code=503,
        )
    return code


async def claim_platform_link_code(code: str) -> LinkCodeClaim:
    """Take code for exactly one in-flight redemption.

    The claim, not the read, makes a redemption single-use: reading alone let two
    deliveries of the same handoff both run the link's side effects. The record
    is untouched, so a refused or broken redemption can release the claim.
    """
    for _ in range(PLATFORM_LINK_CODE_CLAIM_ATTEMPTS):
        claimed = await redis_cache.client.set(
            _claim_key(code),
            PLATFORM_LINK_CODE_CLAIM_HELD,
            nx=True,
            ex=PLATFORM_LINK_CODE_CLAIM_TTL,
        )
        if claimed:
            break
        # Losing the claim has two opposite answers and only the marker's value
        # separates them: a twin redemption still running, or a spent code whose
        # marker outlived the record. A marker gone by now means the code may be live.
        held = await redis_cache.client.get(_claim_key(code))
        if held is not None:
            return LinkCodeClaim(in_flight=held == PLATFORM_LINK_CODE_CLAIM_HELD)
    else:
        # Answering this as linked would tell the bot a link nobody wrote went
        # through; the honest answer is a retryable failure.
        raise create_error(
            message="The link is busy. Please tap it again.",
            why="the one-tap code was claimed and released by concurrent redemptions on every attempt",
            fix="tap the link again; the code is still valid",
            status_code=503,
        )

    payload = await get_cache(_code_key(code), PlatformLinkCodePayload)
    if payload is None:
        await release_platform_link_code(code)
        return LinkCodeClaim()
    return LinkCodeClaim(payload=payload)


async def release_platform_link_code(code: str) -> None:
    """Hand the code back after a redemption that did not write the link."""
    await delete_cache(_claim_key(code))


async def discard_platform_link_code(code: str) -> None:
    """Spend code once the link it authorised has been written.

    The claim becomes a spent marker outliving the record, written first and
    retried like the claim: a blip here is the one failure that becomes a
    replayed greeting. The last RedisError is raised when every attempt fails.
    """
    failures: list[RedisError] = []
    for _ in range(PLATFORM_LINK_CODE_CLAIM_ATTEMPTS):
        try:
            await redis_cache.client.set(
                _claim_key(code), PLATFORM_LINK_CODE_CLAIM_SPENT, ex=PLATFORM_LINK_CODE_TTL
            )
            break
        except RedisError as e:
            failures.append(e)
    else:
        raise failures[-1]
    await delete_cache(_code_key(code))
