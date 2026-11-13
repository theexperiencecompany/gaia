"""What each bot card button does, stored under the opaque id the button carries.

Only the operations' shapes and their storage live here, with no service
imports: minting happens on the outbound delivery path, which the services a
tap runs (HIL, mail) themselves depend on. Performing a tap is card_actions.
"""

from enum import StrEnum
import secrets
from typing import Annotated, Literal

from pydantic import BaseModel, Field, ValidationError

from app.constants.cache import BOT_CARD_ACTION_PREFIX, BOT_CARD_ACTION_TTL, BOT_CARD_PREFIX
from app.constants.log_tags import LogTag
from app.db.redis import delete_cache, get_cache, set_cache
from app.models.chat_models import ToolDataEntry
from shared.py.wide_events import log

#: 12 random bytes -> a 16-char URL-safe id: unguessable, and far inside
#: Telegram's 64-byte callback_data with its prefix.
_ACTION_ID_BYTES = 12


class CardActionKind(StrEnum):
    """What a bot card button does."""

    APPROVE = "approve"
    DENY = "deny"
    SEND_EMAIL = "send_email"


class _CardActionBase(BaseModel):
    user_id: str
    #: The conversation the card was shown in; the tap is recorded there.
    conversation_id: str | None
    #: The stored card the button sits on, settled after the tap (see store_card).
    card_id: str
    #: The card as the model would name it, e.g. 'the approval "Send the deck to Vee"'.
    subject: str


class ApprovalCardAction(_CardActionBase):
    kind: Literal[CardActionKind.APPROVE, CardActionKind.DENY]
    approval_id: str


class SendEmailCardAction(_CardActionBase):
    kind: Literal[CardActionKind.SEND_EMAIL]
    to: list[str] = Field(min_length=1)
    subject_line: str
    body: str
    cc: list[str] | None = None
    bcc: list[str] | None = None
    thread_id: str | None = None
    #: Set only on a draft that must be sent as stored (one with attachments).
    draft_id: str | None = None


CardAction = Annotated[
    ApprovalCardAction | SendEmailCardAction,
    Field(discriminator="kind"),
]


class _StoredCardAction(BaseModel):
    action: CardAction


def _key(action_id: str) -> str:
    return f"{BOT_CARD_ACTION_PREFIX}{action_id}"


async def mint_card_action(action: CardAction) -> str | None:
    """Store what a button does and return its id; None (no button) when Redis is down."""
    action_id = secrets.token_urlsafe(_ACTION_ID_BYTES)
    stored = await set_cache(
        _key(action_id),
        _StoredCardAction(action=action),
        ttl=BOT_CARD_ACTION_TTL,
        model=_StoredCardAction,
    )
    if not stored:
        log.warning(f"{LogTag.API} Bot card action not stored; card sent without the button")
        return None
    return action_id


async def load_card_action(action_id: str) -> CardAction | None:
    """Return the stored operation for a button, or None when unknown, expired or unreadable."""
    try:
        stored = await get_cache(_key(action_id), _StoredCardAction)
    except ValidationError as exc:
        log.error(f"{LogTag.API} Bot card action unreadable", error_type=type(exc).__name__)
        return None
    return stored.action if stored is not None else None


async def spend_card_action(action_id: str) -> None:
    """Retire a button whose operation landed, so a second tap cannot repeat it."""
    await delete_cache(_key(action_id))


class _StoredCard(BaseModel):
    entry: ToolDataEntry


def new_card_id() -> str:
    """Return a fresh id for a card whose buttons are about to be minted."""
    return secrets.token_urlsafe(_ACTION_ID_BYTES)


def _card_key(card_id: str) -> str:
    return f"{BOT_CARD_PREFIX}{card_id}"


async def store_card(card_id: str, entry: ToolDataEntry) -> None:
    """Keep the card as sent, so a tap can return it settled for the bot to redraw.

    A tap carries no state (a Telegram widget query is just who tapped and the
    data), so the card's current state lives here, for as long as its buttons.
    """
    stored = await set_cache(
        _card_key(card_id),
        _StoredCard(entry=entry),
        ttl=BOT_CARD_ACTION_TTL,
        model=_StoredCard,
    )
    if not stored:
        log.warning(f"{LogTag.API} Bot card not stored; a tap will not redraw it")


async def load_card(card_id: str) -> ToolDataEntry | None:
    """Return the card's current state, or None when it expired or was never stored."""
    try:
        stored = await get_cache(_card_key(card_id), _StoredCard)
    except ValidationError as exc:
        log.error(f"{LogTag.API} Bot card unreadable", error_type=type(exc).__name__)
        return None
    return stored.entry if stored is not None else None
