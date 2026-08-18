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
    fetches them itself, either from ``GET /sessions/{conversation_id}/artifacts/{path}``
    using its own (bot-authenticated) session, or directly from ``url`` (a
    CDN-hosted asset, e.g. a signed browser-automation step screenshot) — exactly
    one of the two sources is set."""

    conversation_id: str | None = Field(default=None, min_length=1)
    path: str | None = Field(
        default=None, min_length=1
    )  # artifact path relative to the session's artifacts/
    url: str | None = None  # CDN source; fetched directly, no GAIA auth involved
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
        if has_url and not self.url.startswith("https://"):
            # The URL is the bearer authorization for the attachment bytes, so it
            # must never ride a cleartext hop a network observer could read.
            raise ValueError("attachment `url` must be an https URL")
        return self


class OutboundMessageEnvelope(BaseModel):
    """Shape of a bot-facing message queued to the delivery bus."""

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
    enqueued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _require_text_or_attachment(self) -> Self:
        if not self.text and not self.text_parts and self.attachment is None:
            raise ValueError("envelope requires text, text_parts, or attachment")
        return self
