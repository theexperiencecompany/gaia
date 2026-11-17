"""The comms fast lane: query tokens, the semantic deadline, the rendered block, and the next-turn precompute."""

import asyncio
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
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
from app.utils.background_tasks import spawn_background_task
from tests.helpers import WideEventRecorder

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


#: A semantic budget no scheduler delay can exceed, and one already spent.
_IN_TIME = 5.0
_ALREADY_LATE = 0.0


@dataclass
class _Lane:
    """The lane's patched sources, and the semantic steps it spawned."""

    semantic: AsyncMock
    pinned: AsyncMock
    candidates: AsyncMock
    log: MagicMock
    steps: list[asyncio.Task[list[str]]]


@asynccontextmanager
async def _lane(semantic: AsyncMock, *, budget: float) -> AsyncIterator[_Lane]:
    """Patch the lane's sources; on exit, cancel and await any step still running."""
    steps: list[asyncio.Task[list[str]]] = []

    def spawn(coro: Coroutine[object, object, list[str]], *, name: str) -> asyncio.Task[list[str]]:
        task = spawn_background_task(coro, name=name)
        steps.append(task)
        return task

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
        patch.object(fast_recall, "FAST_RECALL_SEMANTIC_BUDGET_SECONDS", budget),
        patch.object(fast_recall, "spawn_background_task", side_effect=spawn),
        patch.object(fast_recall, "log") as log,
    ):
        try:
            yield _Lane(
                semantic=semantic, pinned=pinned, candidates=candidates, log=log, steps=steps
            )
        finally:
            for step in steps:
                step.cancel()
            if steps:
                await asyncio.wait(steps)


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


async def test_an_embedding_in_time_ranks_its_hits_first() -> None:
    async with _lane(AsyncMock(return_value=["s1"]), budget=_IN_TIME) as lane:
        await _answer()

    lane.semantic.assert_awaited_once_with("u1", QUERY)
    lane.pinned.assert_awaited_once_with("u1", "c1")
    lane.candidates.assert_awaited_once_with(
        "u1", fast_recall.fts_tokens(QUERY), ["p1"], MEMORY_RECALL_BLOCK_LIMIT, semantic_ids=["s1"]
    )
    lane.log.set_ns.assert_not_called()


async def test_a_late_embedding_still_returns_pinned_and_word_matches() -> None:
    async with _lane(_late(asyncio.Event(), ["s1"]), budget=_ALREADY_LATE) as lane:
        entries = await _answer()

    assert entries == [MemoryEntry(content="Lives in Berlin.")]
    lane.candidates.assert_awaited_once_with(
        "u1", fast_recall.fts_tokens(QUERY), ["p1"], MEMORY_RECALL_BLOCK_LIMIT, semantic_ids=[]
    )


async def test_a_late_embedding_is_counted_and_named_on_the_turn() -> None:
    before = REGISTRY.get_sample_value(_SEMANTIC_MISSES) or 0.0

    async with _lane(_late(asyncio.Event(), []), budget=_ALREADY_LATE) as lane:
        await _answer()

    assert REGISTRY.get_sample_value(_SEMANTIC_MISSES) == before + 1
    lane.log.set_ns.assert_called_once_with("memory_fast_recall", semantic="late")


async def test_a_late_embedding_keeps_running_for_the_next_turn() -> None:
    release = asyncio.Event()
    async with _lane(_late(release, ["s1"]), budget=_ALREADY_LATE) as lane:
        await _answer()
        release.set()
        [step] = lane.steps
        await asyncio.wait({step})

    assert step.result() == ["s1"]


async def test_a_late_step_that_fails_is_reported_under_its_task_name() -> None:
    release = asyncio.Event()
    recorder = WideEventRecorder()
    with patch("shared.py.wide_events._loguru", recorder):
        async with _lane(
            _late(release, RuntimeError("vector store down")), budget=_ALREADY_LATE
        ) as lane:
            await _answer()
            release.set()
            [step] = lane.steps
            await asyncio.wait({step})

    event = recorder.event(fast_recall.SEMANTIC_STEP_TASK)
    assert (event["outcome"], event["error_type"], event["error"]) == (
        "failed",
        "RuntimeError",
        "vector store down",
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
