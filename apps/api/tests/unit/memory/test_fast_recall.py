"""The comms fast lane: query tokens, the rendered block, and the next-turn precompute."""

from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from app.agents.context import fetchers
from app.agents.context.section_context import SectionContext
from app.agents.context.tiers import AgentTier
from app.memory import fast_recall
from app.models.memory_models import MemoryEntry, MemorySearchResult


def _comms_ctx() -> SectionContext:
    return SectionContext(
        tier=AgentTier.COMMS, user_id="u1", conversation_id="c1", query="where do I live"
    )


def test_tokens_drop_punctuation_apostrophes_short_words_and_repeats() -> None:
    tokens = fast_recall.fts_tokens("Hey!! What's my flight's SEAT, my seat?")

    assert tokens == ["hey", "whats", "flights", "seat"]


def test_tokens_are_capped() -> None:
    query = " ".join(f"word{i}" for i in range(100))

    assert len(fast_recall.fts_tokens(query)) == fast_recall.FAST_RECALL_MAX_TOKENS


async def test_a_lane_renders_its_memories() -> None:
    entries = [MemoryEntry(content="Lives in Berlin.")]
    with patch.object(
        fetchers.fast_recall, "fast_recall", new=AsyncMock(return_value=entries)
    ) as lane:
        block = await fetchers.build_fast_recall_block(_comms_ctx())

    lane.assert_awaited_once_with("u1", "where do I live", conversation_id="c1")
    assert "Lives in Berlin." in block


async def test_precompute_recalls_on_the_last_exchange_and_pins_what_it_found() -> None:
    found = MemorySearchResult(
        memories=[MemoryEntry(id="m1", content="a"), MemoryEntry(id="m2", content="b")]
    )
    messages = [
        HumanMessage(content="old question"),
        AIMessage(content="old answer"),
        HumanMessage(content="when is my flight"),
        AIMessage(content="Your flight to Berlin is on Friday."),
    ]
    with (
        patch.object(
            fast_recall.memory_engine, "recall", new=AsyncMock(return_value=found)
        ) as recall,
        patch.object(fast_recall, "store_precomputed", new=AsyncMock()) as store,
    ):
        await fast_recall.precompute_next_turn("u1", "c1", messages)

    query = recall.await_args.args[1]
    assert query == "when is my flight\nYour flight to Berlin is on Friday."
    store.assert_awaited_once_with("u1", "c1", ["m1", "m2"])


async def test_precompute_without_an_exchange_does_nothing() -> None:
    with patch.object(fast_recall.memory_engine, "recall", new=AsyncMock()) as recall:
        await fast_recall.precompute_next_turn("u1", "c1", [])

    recall.assert_not_awaited()


async def test_a_failing_lane_costs_only_its_own_section() -> None:
    with patch.object(
        fetchers.fast_recall, "fast_recall", new=AsyncMock(side_effect=ConnectionError("pg down"))
    ):
        block = await fetchers.build_fast_recall_block(_comms_ctx())

    assert block == ""
