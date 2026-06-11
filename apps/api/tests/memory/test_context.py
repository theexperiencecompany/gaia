"""Hot-path core context — the always-injected memory block.

Section structure, the empty-user contract, which documents are (and are
NOT) injected, and graceful behavior when Redis is unavailable. Cache
invalidation through ``retain`` is covered in ``test_consolidation``.
"""

from datetime import UTC, datetime

import pytest

from app.constants.memory import MemoryDocType
from app.db.redis import redis_cache
from app.memory import pg_store
from app.memory.engine import memory_engine

pytestmark = pytest.mark.memory


async def test_core_context_sections_structure_and_order(memory_user: str) -> None:
    await memory_engine.update_document(memory_user, MemoryDocType.USER_MD, "Aryan builds GAIA.")
    await memory_engine.update_document(
        memory_user, MemoryDocType.MEMORY_MD, "Prefers concise answers."
    )
    await memory_engine.update_document(
        memory_user, MemoryDocType.AGENDA_MD, "Ship the memory system."
    )
    await memory_engine.update_document(
        memory_user, MemoryDocType.PEOPLE_MD, "PEOPLE-REGISTER-SENTINEL"
    )
    await memory_engine.update_document(memory_user, MemoryDocType.INSIGHTS_MD, "INSIGHTS-SENTINEL")
    await pg_store.append_episode_entries(
        memory_user,
        datetime.now(UTC).date(),
        [{"time": "08:30", "text": "Started the workday", "source": "conversation"}],
    )

    context = await memory_engine.get_core_context(memory_user)

    user_pos = context.index("## About the user")
    conventions_pos = context.index("## Assistant conventions")
    agenda_pos = context.index("## Current agenda")
    activity_pos = context.index("## Recent activity")
    assert user_pos < conventions_pos < agenda_pos < activity_pos, (
        f"core context sections out of order:\n{context}"
    )

    assert "Aryan builds GAIA." in context
    assert "Prefers concise answers." in context
    assert "Ship the memory system." in context
    assert "- 08:30 Started the workday" in context
    assert f"Today ({datetime.now(UTC).date().isoformat()})" in context

    # people.md and insights.md are retrieval-only — never injected hot.
    assert "PEOPLE-REGISTER-SENTINEL" not in context
    assert "INSIGHTS-SENTINEL" not in context


async def test_core_context_empty_user_returns_empty_string(memory_user: str) -> None:
    assert await memory_engine.get_core_context(memory_user) == ""


async def test_core_context_omits_blank_documents(memory_user: str) -> None:
    await memory_engine.update_document(memory_user, MemoryDocType.USER_MD, "   \n  ")
    await memory_engine.update_document(memory_user, MemoryDocType.AGENDA_MD, "Real agenda.")

    context = await memory_engine.get_core_context(memory_user)
    assert "## About the user" not in context, "blank documents must be omitted"
    assert "## Current agenda" in context


async def test_core_context_survives_redis_outage(
    memory_user: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await memory_engine.update_document(
        memory_user, MemoryDocType.USER_MD, "Aryan is in Bengaluru."
    )
    # Simulate Redis down: the cache layer degrades to no-ops, and the
    # context must still assemble straight from Postgres without raising.
    monkeypatch.setattr(redis_cache, "redis", None)

    context = await memory_engine.get_core_context(memory_user)
    assert "Aryan is in Bengaluru." in context

    # And mutations (which invalidate caches) must not raise either.
    await memory_engine.update_document(
        memory_user, MemoryDocType.USER_MD, "Aryan is in San Francisco."
    )
    fresh = await memory_engine.get_core_context(memory_user)
    assert "Aryan is in San Francisco." in fresh
