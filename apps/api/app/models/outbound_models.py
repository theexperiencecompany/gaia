"""Documents for the outbound delivery pipeline's own collections."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.constants.chat import ConversationSource
from app.db.repositories.base import MongoDocument
from app.schemas.outbound import ReceiptStatus


class OutboundReceiptDocument(MongoDocument):
    """One bot receipt in the ``outbound_receipts`` collection, filed once per (envelope, status)."""

    envelope_id: str
    outbox_message_id: str
    part_index: int
    platform: ConversationSource
    platform_message_ids: list[str]
    status: ReceiptStatus
    error: str | None = None
    occurred_at: datetime
    recorded_at: datetime


class OutboundReceiptUpdate(BaseModel):
    """Receipts are append-only; the base repository still needs an update model to declare."""

    model_config = ConfigDict(extra="forbid")
