"""Schema for the outbound message envelope published to the bot queues.

Mirrors ``OutboundMessageEnvelope`` in
``libs/shared/ts/src/bots/consumer/envelope.ts``. ``text`` is raw CommonMark —
the bot consumer converts it to the platform's native formatting before sending.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field


class OutboundMessageEnvelope(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    platform: str = Field(min_length=1)
    destination_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    enqueued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
