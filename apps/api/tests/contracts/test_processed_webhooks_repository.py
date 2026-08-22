"""Contract tests for ProcessedWebhooksRepository — webhook idempotency.

The unique index on ``webhook_id`` is the real once-only guarantee, so the
fixture creates it on the throwaway collection to mirror production before
asserting that a duplicate webhook is rejected exactly once.
"""

from __future__ import annotations

import pytest

from app.db.repositories.processed_webhooks import ProcessedWebhooksRepository


@pytest.fixture
async def repo(raw_collection) -> ProcessedWebhooksRepository:
    # Mirror the production unique index so idempotency is genuinely enforced.
    await raw_collection.create_index("webhook_id", unique=True)
    return ProcessedWebhooksRepository()


class TestProcessedWebhooksRepository:
    async def test_mark_then_is_processed(self, repo):
        assert await repo.is_processed("wh1") is False
        await repo.mark_processed("wh1", event_type="payment.succeeded", status="processed")
        assert await repo.is_processed("wh1") is True
        assert await repo.is_processed("other") is False

    async def test_duplicate_webhook_rejected_exactly_once(self, repo, raw_collection):
        await repo.mark_processed("dup", event_type="e", status="processed")
        # A second mark for the same id is a silent no-op (unique index rejects it).
        await repo.mark_processed("dup", event_type="e", status="processed")
        assert await raw_collection.count_documents({"webhook_id": "dup"}) == 1
        assert await repo.is_processed("dup") is True

    async def test_stores_result_fields(self, repo, raw_collection):
        await repo.mark_processed(
            "wh2",
            event_type="subscription.active",
            status="processed",
            message="ok",
            payment_id="pay1",
            subscription_id="sub1",
        )
        raw = await raw_collection.find_one({"webhook_id": "wh2"})
        assert raw is not None
        assert raw["event_type"] == "subscription.active"
        assert raw["payment_id"] == "pay1" and raw["subscription_id"] == "sub1"
        assert raw["processed_at"] is not None  # TTL anchor
