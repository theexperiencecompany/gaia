"""Contract tests for OutboundReceiptsRepository — a receipt is filed once per (envelope, status)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.constants.chat import ConversationSource
from app.db.repositories.outbound_receipts import OutboundReceiptsRepository
from app.schemas.outbound import OutboundReceipt, ReceiptStatus


@pytest.fixture
async def repo(raw_collection) -> OutboundReceiptsRepository:
    # Mirror the production unique index so idempotency is genuinely enforced.
    await raw_collection.create_index([("envelope_id", 1), ("status", 1)], unique=True)
    return OutboundReceiptsRepository()


def _receipt(
    status: ReceiptStatus = ReceiptStatus.SENT, envelope_id: str = "env-1"
) -> OutboundReceipt:
    return OutboundReceipt(
        envelope_id=envelope_id,
        outbox_message_id="ob-1",
        part_index=1,
        platform=ConversationSource.TELEGRAM,
        platform_message_ids=["m1", "m2"],
        status=status,
        occurred_at=datetime(2026, 11, 10, 11, 0, tzinfo=UTC),
    )


class TestOutboundReceiptsRepository:
    async def test_a_receipt_is_filed_exactly_once(self, repo, raw_collection):
        assert await repo.record(_receipt()) is True
        assert await repo.record(_receipt()) is False
        assert await raw_collection.count_documents({"envelope_id": "env-1"}) == 1

    async def test_the_stored_receipt_keeps_what_the_bot_reported(self, repo, raw_collection):
        await repo.record(_receipt(ReceiptStatus.FAILED))

        raw = await raw_collection.find_one({"envelope_id": "env-1"})
        assert raw is not None
        assert raw["status"] == "failed"
        assert raw["platform"] == "telegram"
        assert raw["platform_message_ids"] == ["m1", "m2"]
        assert raw["outbox_message_id"] == "ob-1" and raw["part_index"] == 1
        assert raw["recorded_at"] is not None  # TTL anchor

    async def test_one_envelope_may_hold_receipts_of_different_statuses(self, repo):
        assert await repo.record(_receipt(ReceiptStatus.FAILED)) is True
        assert await repo.record(_receipt(ReceiptStatus.SENT)) is True

    async def test_racing_receipts_admit_one(self, repo):
        outcomes = await asyncio.gather(*(repo.record(_receipt()) for _ in range(5)))
        assert sorted(outcomes) == [False, False, False, False, True]
