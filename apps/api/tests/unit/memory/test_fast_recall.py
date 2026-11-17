"""The comms fast lane: query tokens, the semantic deadline, the rendered block, and the next-turn precompute."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from prometheus_client import REGISTRY

from app.agents.context import fetchers
from app.agents.context.section_context import SectionContext
from app.agents.context.tiers import AgentTier
from app.constants.memory import (
    FAST_RECALL_MAX_TOKENS,
    MEMORY_RECALL_BLOCK_LIMIT,
    PRECOMPUTED_RECALL_LIMIT,
)
from app.memory import fast_recall, pg_store
from app.memory.engine import memory_engine
from app.models.memory_models import MemoryEntry, MemorySearchResult

QUERY = "where do I live"
_SEMANTIC_MISSES = "memory_fast_recall_semantic_missed_total"


def _comms_ctx() -> SectionContext:
    return SectionContext(
        tier=AgentTier.COMMS, user_id="u1", conversation_id="c1", query="where do I live"
    )


def test_tokens_drop_punctuation_apostrophes_short_words_and_repeats() -> None:
    tokens = fast_recall.fts_tokens("Hey!! What's my flight's SEAT, my seat?")

    assert tokens == ["hey", "whats", "flights", "seat"]


def test_tokens_are_capped() -> None:
    query = " ".join(f"word{i}" for i in range(100))

    assert len(fast_recall.fts_tokens(query)) == FAST_RECALL_MAX_TOKENS


@dataclass
class _Lane:
    """The lane's patched sources, for asserting what it asked each of them."""

    semantic: AsyncMock
    pinned: AsyncMock
    candidates: AsyncMock
    log: MagicMock


@contextmanager
def _lane(semantic: AsyncMock) -> Iterator[_Lane]:
    """Patch the lane's sources around a given semantic step."""
    with (
        patch.object(fast_recall, "_semantic_ids", new=semantic),
        patch.object(fast_recall, "_pinned_ids", new=AsyncMock(return_value=["p1"])) as pinned,
        patch.object(
            pg_store, "fast_candidates", new=AsyncMock(return_value=[MagicMock()])
        ) as candidates,
        patch.object(
            fast_recall,
            "build_entries",
            new=AsyncMock(return_value=[MemoryEntry(content="Lives in Berlin.")]),
        ),
        patch.object(fast_recall, "FAST_RECALL_SEMANTIC_BUDGET_SECONDS", 0.01),
        patch.object(fast_recall, "log") as log,
    ):
        yield _Lane(semantic=semantic, pinned=pinned, candidates=candidates, log=log)


async def _answer() -> list[MemoryEntry]:
    """Run the lane, bounded so a lane that waits out a late embedding fails instead of hangs."""
    return await asyncio.wait_for(
        fast_recall.fast_recall("u1", QUERY, conversation_id="c1"), timeout=1
    )


def _late(release: asyncio.Event, result: list[str] | Exception) -> AsyncMock:
    """Build a semantic step that answers only once released: after the lane has moved on."""

    async def step(_user_id: str, _query: str) -> list[str]:
        await release.wait()
        if isinstance(result, Exception):
            raise result
        return result

    return AsyncMock(side_effect=step)


async def _settle() -> None:
    """Let a released step finish and its done-callbacks run."""
    for _ in range(3):
        await asyncio.sleep(0)


async def test_an_embedding_in_time_ranks_its_hits_first() -> None:
    with _lane(AsyncMock(return_value=["s1"])) as lane:
        await _answer()

    lane.semantic.assert_awaited_once_with("u1", QUERY)
    lane.pinned.assert_awaited_once_with("u1", "c1")
    lane.candidates.assert_awaited_once_with(
        "u1", fast_recall.fts_tokens(QUERY), ["p1"], MEMORY_RECALL_BLOCK_LIMIT, semantic_ids=["s1"]
    )
    lane.log.set_ns.assert_not_called()


async def test_a_late_embedding_still_returns_pinned_and_word_matches() -> None:
    with _lane(_late(asyncio.Event(), ["s1"])) as lane:
        entries = await _answer()

    assert entries == [MemoryEntry(content="Lives in Berlin.")]
    lane.candidates.assert_awaited_once_with(
        "u1", fast_recall.fts_tokens(QUERY), ["p1"], MEMORY_RECALL_BLOCK_LIMIT, semantic_ids=[]
    )


async def test_a_late_embedding_is_counted_and_named_on_the_turn() -> None:
    before = REGISTRY.get_sample_value(_SEMANTIC_MISSES) or 0.0

    with _lane(_late(asyncio.Event(), [])) as lane:
        await _answer()

    assert REGISTRY.get_sample_value(_SEMANTIC_MISSES) == before + 1
    lane.log.set_ns.assert_called_once_with("memory_fast_recall", semantic="late")


async def test_a_late_embedding_keeps_running_for_the_next_turn() -> None:
    release = asyncio.Event()
    with _lane(_late(release, ["s1"])) as lane:
        await _answer()
        release.set()
        await _settle()

    lane.semantic.assert_awaited_once()
    lane.log.warning.assert_not_called()


async def test_a_late_step_that_fails_is_logged_not_lost() -> None:
    release = asyncio.Event()
    with _lane(_late(release, RuntimeError("vector store down"))) as lane:
        await _answer()
        release.set()
        await _settle()

    lane.log.warning.assert_called_once_with(
        "Late semantic step failed after the lane answered",
        error="vector store down",
        error_type="RuntimeError",
    )


async def test_a_lane_renders_its_memories() -> None:
    entries = [MemoryEntry(content="Lives in Berlin.")]
    with patch.object(fast_recall, "fast_recall", new=AsyncMock(return_value=entries)) as lane:
        block = await fetchers.build_fast_recall_block(_comms_ctx())

    lane.assert_awaited_once_with("u1", "where do I live", conversation_id="c1")
    assert "Lives in Berlin." in block


async def test_precompute_recalls_on_the_last_exchange_and_pins_what_it_found() -> None:
    found = MemorySearchResult(
        memories=[MemoryEntry(id="m1", content="a"), MemoryEntry(id="m2", content="b")]
    )
    messages: list[AnyMessage] = [
        HumanMessage(content="old question"),
        AIMessage(content="old answer"),
        HumanMessage(content="when is my flight"),
        AIMessage(content="Your flight to Berlin is on Friday."),
    ]
    with (
        patch.object(memory_engine, "recall", new=AsyncMock(return_value=found)) as recall,
        patch.object(fast_recall, "store_precomputed", new=AsyncMock()) as store,
    ):
        await fast_recall.precompute_next_turn("u1", "c1", messages)

    recall.assert_awaited_once_with(
        "u1",
        "when is my flight\nYour flight to Berlin is on Friday.",
        limit=PRECOMPUTED_RECALL_LIMIT,
    )
    store.assert_awaited_once_with("u1", "c1", ["m1", "m2"])


async def test_precompute_without_an_exchange_does_nothing() -> None:
    with patch.object(memory_engine, "recall", new=AsyncMock()) as recall:
        await fast_recall.precompute_next_turn("u1", "c1", [])

    recall.assert_not_awaited()


async def test_a_failing_lane_costs_only_its_own_section() -> None:
    with patch.object(
        fast_recall, "fast_recall", new=AsyncMock(side_effect=ConnectionError("pg down"))
    ):
        block = await fetchers.build_fast_recall_block(_comms_ctx())

    assert block == ""
