"""Schema for the outbound message envelope published to the bot queues.

Mirrors ``OutboundMessageEnvelope`` in
``libs/shared/ts/src/bots/consumer/envelope.ts``. ``text`` is raw CommonMark —
the bot consumer converts it to the platform's native formatting before sending.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Self
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class OutboundAttachment(BaseModel):
    """A file the bot should deliver. The bytes are NOT in the envelope — the bot
    fetches them from ``GET /sessions/{conversation_id}/artifacts/{path}`` using
    its own (bot-authenticated) session, then uploads them to the platform."""

    conversation_id: str = Field(min_length=1)
    path: str = Field(min_length=1)  # artifact path relative to the session's artifacts/
    filename: str = Field(min_length=1)
    content_type: str | None = None
    caption: str | None = None


class OutboundAction(BaseModel):
    """An interactive button the bot renders alongside the message (e.g. a
    Telegram inline-keyboard button). ``callback_data`` is the opaque token the
    bot posts back when the button is tapped — for todo approvals it is
    ``todo_approve:<todo_id>`` / ``todo_dismiss:<todo_id>``."""

    label: str = Field(min_length=1)
    callback_data: str = Field(min_length=1)


class OutboundMessageEnvelope(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    platform: str = Field(min_length=1)
    destination_id: str = Field(min_length=1)
    # A message carries a single ``text`` body, an ordered ``text_parts`` group,
    # an attachment, or a combination. ``text_parts`` is how a multi-bubble
    # notification (e.g. a workflow completion: header, result messages, footer)
    # is delivered as ONE queue unit so the consumer sends its bubbles in order —
    # publishing them as separate envelopes would let a concurrent consumer
    # reorder them.
    text: str | None = Field(default=None, min_length=1)
    text_parts: list[str] | None = None
    attachment: OutboundAttachment | None = None
    # Optional interactive buttons attached to the message. Omitted from the wire
    # payload when unset (see ``outbound_delivery._serialize``) so envelopes
    # without actions remain byte-identical to the pre-actions format.
    actions: list[OutboundAction] | None = None
    enqueued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _require_text_or_attachment(self) -> Self:
        if not self.text and not self.text_parts and self.attachment is None:
            raise ValueError("envelope requires text, text_parts, or attachment")
        return self
