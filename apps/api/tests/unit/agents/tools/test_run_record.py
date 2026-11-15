"""A run's per-integration block: set after its connect card, lifted once the user connects."""

from __future__ import annotations

import fakeredis.aioredis

from app.agents.tools import run_record


async def test_a_connect_lifts_only_the_integration_it_was_for(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await run_record.block_integration("stream-1", "gmail")
    await run_record.block_integration("stream-1", "slack")

    await run_record.unblock_integration("stream-1", "gmail")

    assert await run_record.is_integration_blocked("stream-1", "gmail") is False
    assert await run_record.is_integration_blocked("stream-1", "slack") is True
