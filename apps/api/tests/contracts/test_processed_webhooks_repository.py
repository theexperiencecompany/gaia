"""Contract tests for ProcessedWebhooksRepository — webhook idempotency.

The unique index on ``webhook_id`` is the real once-only guarantee, so the
fixture creates it on the throwaway collection to mirror production before
asserting that a delivery can be claimed exactly once.
"""

from __future__ import annotations

import asyncio

import pytest

from app.db.repositories.processed_webhooks import (
    CLAIMED_STATUS,
    ProcessedWebhooksRepository,
)
from app.models.payment_models import ProcessedWebhookUpdate


@pytest.fixture
async def repo(raw_collection) -> ProcessedWebhooksRepository:
    # Mirror the production unique index so idempotency is genuinely enforced.
    await raw_collection.create_index("webhook_id", unique=True)
    return ProcessedWebhooksRepository()


class TestProcessedWebhooksRepository:
    async def test_a_delivery_is_claimed_exactly_once(self, repo, raw_collection):
        assert await repo.claim("wh1", event_type="payment.succeeded") is True
        assert await repo.claim("wh1", event_type="payment.succeeded") is False
        assert await repo.claim("other", event_type="payment.succeeded") is True
        assert await raw_collection.count_documents({"webhook_id": "wh1"}) == 1

    async def test_racing_claims_admit_one(self, repo, raw_collection):
        outcomes = await asyncio.gather(*(repo.claim("race", event_type="e") for _ in range(5)))
        assert sorted(outcomes) == [False, False, False, False, True]
        assert await raw_collection.count_documents({"webhook_id": "race"}) == 1

    async def test_outcome_is_written_onto_the_claim(self, repo, raw_collection):
        await repo.claim("wh2", event_type="subscription.active")
        before = await raw_collection.find_one({"webhook_id": "wh2"})
        assert before is not None and before["status"] == CLAIMED_STATUS

        await repo.record_outcome(
            "wh2",
            ProcessedWebhookUpdate(
                status="processed", message="ok", payment_id="pay1", subscription_id="sub1"
            ),
        )
        raw = await raw_collection.find_one({"webhook_id": "wh2"})
        assert raw is not None
        assert raw["event_type"] == "subscription.active"
        assert raw["status"] == "processed"
        assert raw["payment_id"] == "pay1" and raw["subscription_id"] == "sub1"
        assert raw["processed_at"] is not None  # TTL anchor

    async def test_a_released_claim_can_be_taken_again(self, repo):
        assert await repo.claim("retry", event_type="e") is True
        await repo.release("retry")
        assert await repo.claim("retry", event_type="e") is True
