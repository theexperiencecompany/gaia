"""Schema for the outbound message envelope published to the bot queues.

Mirrors ``OutboundMessageEnvelope`` in
``libs/shared/ts/src/bots/consumer/envelope.ts``. ``text`` is raw CommonMark —
the bot consumer converts it to the platform's native formatting before sending.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from app.config.settings import settings
from app.constants.chat import BOT_CONVERSATION_SOURCES, ConversationSource
from app.constants.outbound import OUTBOUND_ENVELOPE_VERSION


def _is_own_api(url: str) -> bool:
    """Whether this URL is served by this API (HOST), compared by origin rather than prefix."""
    target, own = urlsplit(url), urlsplit(settings.HOST)
    return bool(own.netloc) and (target.scheme, target.netloc) == (own.scheme, own.netloc)


class OutboundAttachment(BaseModel):
    """A file the bot should deliver. The bytes are NOT in the envelope — the bot
    fetches them itself, either from ``GET /sessions/{conversation_id}/artifacts/{path}``
    using its own (bot-authenticated) session, or directly from ``url`` (a
    CDN-hosted asset, e.g. a signed browser-automation step screenshot) — exactly
    one of the two sources is set."""

    conversation_id: str | None = Field(default=None, min_length=1)
    path: str | None = Field(
        default=None, min_length=1
    )  # artifact path relative to the session's artifacts/
    url: str | None = None  # a CDN asset, or this API serving the bytes itself
    filename: str = Field(min_length=1)
    content_type: str | None = None
    caption: str | None = None

    @model_validator(mode="after")
    def _require_exactly_one_source(self) -> Self:
        has_url = bool(self.url)
        has_artifact = bool(self.conversation_id and self.path)
        if has_url == has_artifact:  # both set or neither set
            raise ValueError(
                "attachment requires exactly one of `url` or (`conversation_id` + `path`)"
            )
        if has_url and not self.url.startswith("https://") and not _is_own_api(self.url):
            # A third-party URL IS the authorization for the bytes, so it must
            # never ride a cleartext hop. Our own API is not: the bot authenticates
            # that fetch, so the URL carries no secret.
            raise ValueError("attachment `url` must be an https URL")
        return self


class OutboundReaction(BaseModel):
    """A native emoji reaction the bot should attach to an existing platform
    message (a comms ``<EMOJI>…</EMOJI>`` answer to a background update).

    ``target_platform_message_id`` is the platform-native id of the message to
    react to (WhatsApp wamid, Telegram message_id, Discord id, Slack ts),
    recorded from the inbound turn. The consumer falls back to sending the
    emoji as a text bubble when the platform cannot attach it."""

    target_platform_message_id: str = Field(min_length=1)
    emoji: str = Field(min_length=1)


class OutboundMessageEnvelope(BaseModel):
    """Shape of a bot-facing message queued to the delivery bus."""

    v: int = OUTBOUND_ENVELOPE_VERSION
    id: str = Field(default_factory=lambda: str(uuid4()))
    # The outbox ledger message this envelope delivers; with part_index it is the
    # bot's dedupe key and the key its receipts are filed under.
    outbox_message_id: str | None = Field(default=None, min_length=1)
    conversation_id: str | None = Field(default=None, min_length=1)
    reply_to_platform_message_id: str | None = Field(default=None, min_length=1)
    edit_of_platform_message_id: str | None = Field(default=None, min_length=1)
    part_index: int = Field(default=0, ge=0)
    platform: str = Field(min_length=1)
    destination_id: str = Field(min_length=1)
    # False (default): destination_id is the user's DM target. True: it is a
    # channel/group id and the bot must send to the channel — some platforms
    # (Discord, Slack) address a channel differently from a user DM.
    is_channel: bool = False
    # A message carries text, an ordered text_parts group, an attachment, or a
    # combination. text_parts keeps a multi-bubble notification as ONE queue
    # unit so a concurrent consumer can't reorder the bubbles.
    text: str | None = Field(default=None, min_length=1)
    text_parts: list[str] | None = None
    attachment: OutboundAttachment | None = None
    reaction: OutboundReaction | None = None
    enqueued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _require_text_or_attachment(self) -> Self:
        if (
            not self.text
            and not self.text_parts
            and self.attachment is None
            and self.reaction is None
        ):
            raise ValueError("envelope requires text, text_parts, attachment, or reaction")
        return self

    @model_validator(mode="after")
    def _edit_requires_text(self) -> Self:
        if self.edit_of_platform_message_id and not (self.text or self.text_parts):
            raise ValueError("an edit requires text or text_parts")
        return self


class ReceiptStatus(StrEnum):
    """How an outbound envelope part ended, as the bot reports it."""

    SENT = "sent"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"


class OutboundReceipt(BaseModel):
    """A bot's report of how one envelope part ended; mirrors receipts.ts in the bot lib.

    platform_message_ids holds every platform message sent for the part, in order
    (empty when none went out). A part with no receipt is unknown, not failed.
    """

    envelope_id: str = Field(min_length=1)
    outbox_message_id: str = Field(min_length=1)
    part_index: int = Field(default=0, ge=0)
    platform: ConversationSource
    platform_message_ids: list[str] = Field(default_factory=list)
    status: ReceiptStatus
    error: str | None = None
    occurred_at: datetime

    @model_validator(mode="after")
    def _bot_platform_only(self) -> Self:
        if self.platform not in BOT_CONVERSATION_SOURCES:
            raise ValueError(f"{self.platform.value} is not a messaging-platform bot")
        return self
