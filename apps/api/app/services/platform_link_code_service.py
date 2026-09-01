"""One-tap platform-linking codes, minted by the web during onboarding.

The mirror image of ``platform_link_token`` (``endpoints/bot.py``), which the
BOT mints and the WEB redeems: here the WEB mints a code bound to the user, the
user carries it to the platform (invisibly in a Telegram deep link, visibly as a
trailing ``#code`` in the WhatsApp/iMessage message they send), and the BOT
redeems it on first contact. Nobody has to type ``/auth``.

Security properties match ``connect_link_service``: 128-bit opaque code, the
binding lives server-side, single-use via ``GETDEL``, bounded TTL.
"""

import secrets
from urllib.parse import quote

from pydantic import BaseModel

from app.config.settings import settings
from app.constants.auth import PLATFORM_LINK_CODE_BYTES
from app.constants.cache import PLATFORM_LINK_CODE_PREFIX, PLATFORM_LINK_CODE_TTL
from app.db.redis import get_and_delete_cache, set_cache
from app.services.platform_link_service import Platform
from app.utils.errors import create_error


class PlatformLinkCodePayload(BaseModel):
    """What a live link code resolves to."""

    user_id: str
    first_message: str


def _code_key(code: str) -> str:
    return f"{PLATFORM_LINK_CODE_PREFIX}:{code}"


def build_handoff_text(first_message: str, code: str) -> str:
    """The exact text a WhatsApp/iMessage user sends: the message plus its code.

    The adapters strip the ``#<code>`` suffix back off before the text reaches
    the agent, so the trailing separator here is part of the wire format.
    """
    return f"{first_message} #{code}"


def build_handoff_links(code: str, first_message: str) -> dict[str, str]:
    """Deep links that carry ``code`` to each platform the onboarding offers.

    iMessage is absent by construction: its number is assigned per user out of
    Photon's shared pool by ``start_platform_connect``, so no link exists until
    the user has registered a phone. The client builds that one from
    ``handoff_text`` and the ``contact_number`` that call returns.
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


async def mint_platform_link_code(user_id: str, first_message: str) -> str:
    """Bind a fresh single-use code to ``user_id`` and their composed first message."""
    code = secrets.token_urlsafe(PLATFORM_LINK_CODE_BYTES)
    stored = await set_cache(
        _code_key(code),
        PlatformLinkCodePayload(user_id=user_id, first_message=first_message).model_dump(),
        ttl=PLATFORM_LINK_CODE_TTL,
    )
    if not stored:
        # Handing out a code nothing can resolve would strand the user on a bot
        # that says "expired" the moment they arrive.
        raise create_error(
            message="Could not start platform linking. Please retry.",
            why="the link code could not be stored (Redis unavailable)",
            fix="retry in a moment, or connect the platform from settings with /auth",
            status_code=503,
        )
    return code


async def consume_platform_link_code(code: str) -> PlatformLinkCodePayload | None:
    """Atomically consume ``code``, returning its binding or None if it is not live.

    ``GETDEL`` enforces single-use: a replay, a second tap, or a brute-force hit
    racing the real user all get nothing.
    """
    return await get_and_delete_cache(_code_key(code), PlatformLinkCodePayload)
