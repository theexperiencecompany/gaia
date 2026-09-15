"""Repository for the ``processed_webhooks`` collection — webhook idempotency.

Global, keyed by the business ``webhook_id``. The unique index on ``webhook_id``
is the once-only guarantee: a delivery is *claimed* by inserting its record
before any handler runs, so two deliveries of the same id (sequential or
racing) can never both act. A 30-day TTL on ``processed_at`` reaps old records.
"""

from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError

from app.db.repositories.base import MongoRepository
from app.models.payment_models import ProcessedWebhookDocument, ProcessedWebhookUpdate

CLAIMED_STATUS = "processing"


class ProcessedWebhooksRepository(
    MongoRepository[ProcessedWebhookDocument, ProcessedWebhookUpdate]
):
    collection_name = "processed_webhooks"
    document_model = ProcessedWebhookDocument
    update_model = ProcessedWebhookUpdate
    uses_object_id = True
    identity_field = "webhook_id"
    cache_policy = None

    async def claim(self, webhook_id: str, *, event_type: str) -> bool:
        """Take ownership of a delivery before handling it.

        False means another delivery of the same id already owns it (or has
        finished): the unique index decided, atomically, on the server.
        """
        document = ProcessedWebhookDocument(
            webhook_id=webhook_id,
            event_type=event_type,
            status=CLAIMED_STATUS,
            processed_at=datetime.now(UTC),
        )
        try:
            await self.create(document)
        except DuplicateKeyError:
            return False
        return True

    async def record_outcome(self, webhook_id: str, outcome: ProcessedWebhookUpdate) -> None:
        """Write the handler's result onto the claim."""
        await self.update(webhook_id, outcome)

    async def release(self, webhook_id: str) -> None:
        """Give a claim back after the handler failed, so the sender's retry
        gets a clean run instead of an "already processed" skip."""
        await self.delete(webhook_id)


processed_webhook_repository = ProcessedWebhooksRepository()
