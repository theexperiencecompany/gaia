"""Repository for the ``processed_webhooks`` collection — webhook idempotency.

Global, keyed by the business ``webhook_id``. A unique index on ``webhook_id``
is the real once-only guarantee; ``mark_processed`` treats a duplicate as a no-op
(the guarantee working). A 30-day TTL on ``processed_at`` reaps old records.
"""

import contextlib
from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError

from app.db.repositories.base import MongoRepository
from app.models.payment_models import ProcessedWebhookDocument, ProcessedWebhookUpdate


class ProcessedWebhooksRepository(
    MongoRepository[ProcessedWebhookDocument, ProcessedWebhookUpdate]
):
    collection_name = "processed_webhooks"
    document_model = ProcessedWebhookDocument
    update_model = ProcessedWebhookUpdate
    uses_object_id = True
    identity_field = "webhook_id"
    cache_policy = None

    async def is_processed(self, webhook_id: str) -> bool:
        return await self._count({"webhook_id": webhook_id}) > 0

    async def mark_processed(
        self,
        webhook_id: str,
        *,
        event_type: str,
        status: str,
        message: str | None = None,
        payment_id: str | None = None,
        subscription_id: str | None = None,
    ) -> None:
        """Record a webhook as processed. A duplicate ``webhook_id`` is a no-op —
        the idempotency guarantee (unique index) working as intended."""
        document = ProcessedWebhookDocument(
            webhook_id=webhook_id,
            event_type=event_type,
            status=status,
            message=message,
            payment_id=payment_id,
            subscription_id=subscription_id,
            processed_at=datetime.now(UTC),
        )
        with contextlib.suppress(DuplicateKeyError):
            await self.create(document)


processed_webhook_repository = ProcessedWebhooksRepository()
