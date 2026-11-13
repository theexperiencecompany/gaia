"""Repository for the outbound_receipts collection — what the bots report about each envelope part.

A receipt is filed once per (envelope_id, status): the unique index is the
idempotency check, so a receipt redelivered by the broker is recognised and
dropped instead of recorded twice.
"""

from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError

from app.db.repositories.base import MongoRepository
from app.models.outbound_models import OutboundReceiptDocument, OutboundReceiptUpdate
from app.schemas.outbound import OutboundReceipt


class OutboundReceiptsRepository(MongoRepository[OutboundReceiptDocument, OutboundReceiptUpdate]):
    collection_name = "outbound_receipts"
    document_model = OutboundReceiptDocument
    update_model = OutboundReceiptUpdate
    uses_object_id = True
    cache_policy = None

    async def record(self, receipt: OutboundReceipt) -> bool:
        """File a receipt; False when this envelope already has one with this status."""
        document = OutboundReceiptDocument(**receipt.model_dump(), recorded_at=datetime.now(UTC))
        try:
            await self.create(document)
        except DuplicateKeyError:
            return False
        return True

    async def outbox_message_ids_of(self, platform_message_id: str) -> list[str]:
        """Return the outbox messages one platform message was sent as a part of."""
        return await self._raw_collection().distinct(
            "outbox_message_id", {"platform_message_ids": platform_message_id}
        )


outbound_receipts_repository = OutboundReceiptsRepository()
