"""Unit tests for app.memory.ingestion — the memory write path.

Every external boundary (Postgres, Chroma, the embedding/extraction models,
the projection and consolidation schedulers) is mocked; the reconciliation
application, chunking, journaling and scheduling logic under test is real.

``insert_memories`` is faked to populate ``record.id`` the way a real flush
does, because the Chroma vector ids are derived from it after the insert.
"""

from dataclasses import dataclass, field
from datetime import UTC, date as date_type, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from app.constants.memory import (
    CATEGORY_PATH_MAX_DEPTH,
    DEFAULT_MEMORY_IMPORTANCE,
    FREE_MEMORY_CAP_COUNT_SAFETY_MARGIN,
    FREE_MEMORY_FACT_LIMIT,
    RECENT_FACTS_LIMIT,
    TRANSCRIPT_CHUNK_MAX_CHARS,
    TRANSCRIPT_CHUNK_OVERLAP_CHARS,
    TRANSCRIPT_CHUNK_TURNS,
    TRANSCRIPT_CHUNKS_PER_SESSION_CAP,
    MemoryDocType,
    MemoryKind,
    MemoryRelationType,
    MemorySourceType,
    ReconcileOutcome,
)
from app.memory import ingestion
from app.memory.ingestion import (
    MemoryLimitReachedError,
    RetainResult,
    retain,
    retain_single,
    summarize_episode,
)
from app.memory.reconciliation import ReconciledFact
from app.memory.schemas import (
    ExtractedEdge,
    ExtractedEntity,
    ExtractedFact,
    ExtractedMemoryBatch,
    FactCategorization,
)
from app.models.memory_db_models import MemoryRecord
from app.models.payment_models import PlanType

USER = "user-1"


def make_fact(
    content: str = "sam likes green tea",
    *,
    kind: MemoryKind = MemoryKind.FACT,
    category_path: str = "preferences",
    importance: float = 0.5,
    entities: list[ExtractedEntity] | None = None,
    edges: list[ExtractedEdge] | None = None,
    occurred_start: datetime | None = None,
    occurred_end: datetime | None = None,
    forget_after: datetime | None = None,
) -> ExtractedFact:
    return ExtractedFact(
        content=content,
        kind=kind,
        category_path=category_path,
        importance=importance,
        entities=entities or [],
        edges=edges or [],
        occurred_start=occurred_start,
        occurred_end=occurred_end,
        forget_after=forget_after,
    )


def make_reconciled(
    fact: ExtractedFact,
    outcome: ReconcileOutcome = ReconcileOutcome.NEW,
    *,
    embedding: list[float] | None = None,
    target_memory_id: str | None = None,
) -> ReconciledFact:
    return ReconciledFact(
        fact=fact,
        embedding=embedding if embedding is not None else [0.1, 0.2],
        outcome=outcome,
        target_memory_id=target_memory_id,
    )


def make_row(
    *,
    content: str = "an existing memory",
    category_path: str = "preferences",
    row_id: uuid.UUID | None = None,
) -> MemoryRecord:
    row = MemoryRecord(
        user_id=USER,
        kind=MemoryKind.FACT.value,
        content=content,
        category_path=category_path,
        source_type=MemorySourceType.CONVERSATION.value,
        importance=DEFAULT_MEMORY_IMPORTANCE,
    )
    row.id = row_id or uuid.uuid4()
    row.created_at = datetime.now(UTC)
    return row


def make_episode(
    *, summary: str | None = None, entries: list[dict[str, str]] | None = None
) -> MagicMock:
    episode = MagicMock()
    episode.summary = summary
    episode.entries = entries if entries is not None else []
    return episode


@dataclass
class Boundaries:
    """Every mocked edge of the ingestion pipeline, for assertion."""

    get_folder_tree: AsyncMock
    get_recent_facts: AsyncMock
    get_episode: AsyncMock
    get_memories_by_ids: AsyncMock
    insert_memories: AsyncMock
    supersede_memory: AsyncMock
    get_memory: AsyncMock
    get_entities_for_memories: AsyncMock
    upsert_entities: AsyncMock
    link_entities: AsyncMock
    insert_edges: AsyncMock
    append_episode_entries: AsyncMock
    get_unsummarized_episode_dates: AsyncMock
    set_episode_summary: AsyncMock
    count_live_memories: AsyncMock
    get_cached_live_count: AsyncMock
    set_cached_live_count: AsyncMock
    adjust_live_count: AsyncMock
    get_cached_plan_type: AsyncMock
    upsert_memories: AsyncMock
    set_memory_flags: AsyncMock
    upsert_conversation_chunks: AsyncMock
    upsert_episode: AsyncMock
    embed_batch: AsyncMock
    embed_query: AsyncMock
    extract_memories: AsyncMock
    categorize_fact: AsyncMock
    summarize_episode_entries: AsyncMock
    reconcile: AsyncMock
    invalidate_caches: AsyncMock
    schedule_vfs_sync: MagicMock
    schedule_consolidation: AsyncMock
    inserted_records: list[MemoryRecord] = field(default_factory=list)

    @property
    def chunk_documents(self) -> list[str]:
        if not self.upsert_conversation_chunks.await_args_list:
            return []
        return [
            item["document"]
            for call in self.upsert_conversation_chunks.await_args_list
            for item in call.args[0]
        ]

    @property
    def vector_items(self) -> list[dict[str, Any]]:
        return [
            item for call in self.upsert_memories.await_args_list for item in (call.args[0] or [])
        ]


@pytest.fixture
def boundaries() -> Any:
    """Patch every I/O edge of ingestion with permissive defaults."""
    inserted: list[MemoryRecord] = []

    async def fake_insert(records: list[MemoryRecord]) -> list[MemoryRecord]:
        # Mirror the real flush: the DB default populates `id` on insert, and
        # the Chroma vector ids are read off the records afterwards.
        for record in records:
            if record.id is None:
                record.id = uuid.uuid4()
        inserted.extend(records)
        return records

    async def fake_embed_batch(texts: list[str]) -> list[list[float]]:
        return [[float(index), 0.5] for index, _ in enumerate(texts)]

    patches = {
        "get_folder_tree": AsyncMock(return_value=[]),
        "get_recent_facts": AsyncMock(return_value=[]),
        "get_episode": AsyncMock(return_value=None),
        "get_memories_by_ids": AsyncMock(return_value=[]),
        "supersede_memory": AsyncMock(return_value=None),
        "get_memory": AsyncMock(return_value=None),
        "get_entities_for_memories": AsyncMock(return_value={}),
        "upsert_entities": AsyncMock(return_value={}),
        "link_entities": AsyncMock(return_value=None),
        "insert_edges": AsyncMock(return_value=0),
        "append_episode_entries": AsyncMock(return_value=None),
        "get_unsummarized_episode_dates": AsyncMock(return_value=[]),
        "set_episode_summary": AsyncMock(return_value=None),
        "count_live_memories": AsyncMock(return_value=0),
    }
    chroma_patches = {
        "upsert_memories": AsyncMock(return_value=None),
        "set_memory_flags": AsyncMock(return_value=None),
        "upsert_conversation_chunks": AsyncMock(return_value=None),
        "upsert_episode": AsyncMock(return_value=None),
    }
    cap_patches = {
        "get_cached_live_count": AsyncMock(return_value=None),
        "set_cached_live_count": AsyncMock(return_value=None),
        "adjust_live_count": AsyncMock(return_value=None),
    }
    plan_mock = AsyncMock(return_value=PlanType.PRO)
    insert_mock = AsyncMock(side_effect=fake_insert)
    embed_batch_mock = AsyncMock(side_effect=fake_embed_batch)
    module_patches = {
        "embed_batch": embed_batch_mock,
        "embed_query": AsyncMock(return_value=[0.9, 0.9]),
        "extract_memories": AsyncMock(return_value=ExtractedMemoryBatch()),
        "categorize_fact": AsyncMock(return_value=None),
        "summarize_episode_entries": AsyncMock(return_value="a summary"),
        "reconcile": AsyncMock(return_value=[]),
        "invalidate_user_memory_caches": AsyncMock(return_value=None),
        "schedule_consolidation": AsyncMock(return_value=None),
    }
    vfs_mock = MagicMock(return_value=None)

    with (
        patch.multiple(ingestion.pg_store, insert_memories=insert_mock, **patches),
        patch.multiple(ingestion.chroma_store, **chroma_patches),
        patch.multiple(ingestion.cap_counter, **cap_patches),
        patch.multiple(ingestion, schedule_memory_vfs_sync=vfs_mock, **module_patches),
        # Paid plan -> the free memory cap never applies, so these tests exercise
        # ingestion itself without the cap's plan/count lookups reaching real infra.
        patch.object(ingestion.payment_service, "get_cached_plan_type", plan_mock),
    ):
        yield Boundaries(
            get_folder_tree=patches["get_folder_tree"],
            get_recent_facts=patches["get_recent_facts"],
            get_episode=patches["get_episode"],
            get_memories_by_ids=patches["get_memories_by_ids"],
            insert_memories=insert_mock,
            supersede_memory=patches["supersede_memory"],
            get_memory=patches["get_memory"],
            get_entities_for_memories=patches["get_entities_for_memories"],
            upsert_entities=patches["upsert_entities"],
            link_entities=patches["link_entities"],
            insert_edges=patches["insert_edges"],
            append_episode_entries=patches["append_episode_entries"],
            get_unsummarized_episode_dates=patches["get_unsummarized_episode_dates"],
            set_episode_summary=patches["set_episode_summary"],
            count_live_memories=patches["count_live_memories"],
            get_cached_live_count=cap_patches["get_cached_live_count"],
            set_cached_live_count=cap_patches["set_cached_live_count"],
            adjust_live_count=cap_patches["adjust_live_count"],
            get_cached_plan_type=plan_mock,
            upsert_memories=chroma_patches["upsert_memories"],
            set_memory_flags=chroma_patches["set_memory_flags"],
            upsert_conversation_chunks=chroma_patches["upsert_conversation_chunks"],
            upsert_episode=chroma_patches["upsert_episode"],
            embed_batch=embed_batch_mock,
            embed_query=module_patches["embed_query"],
            extract_memories=module_patches["extract_memories"],
            categorize_fact=module_patches["categorize_fact"],
            summarize_episode_entries=module_patches["summarize_episode_entries"],
            reconcile=module_patches["reconcile"],
            invalidate_caches=module_patches["invalidate_user_memory_caches"],
            schedule_vfs_sync=vfs_mock,
            schedule_consolidation=module_patches["schedule_consolidation"],
            inserted_records=inserted,
        )


class TestClampCategoryPath:
    def test_missing_path_falls_back_to_general(self) -> None:
        assert ingestion._clamp_category_path(None) == "general"
        assert ingestion._clamp_category_path("") == "general"

    def test_truncates_to_the_maximum_tree_depth(self) -> None:
        clamped = ingestion._clamp_category_path("a/b/c/d/e")
        assert clamped == "a/b/c"
        assert len(clamped.split("/")) == CATEGORY_PATH_MAX_DEPTH

    def test_path_at_the_depth_limit_is_preserved(self) -> None:
        assert ingestion._clamp_category_path("work/gaia/memory") == "work/gaia/memory"

    def test_empty_segments_are_dropped_not_counted(self) -> None:
        assert ingestion._clamp_category_path("a//b") == "a/b"
        assert ingestion._clamp_category_path("/leading/slash/x/y") == "leading/slash/x"

    def test_path_of_only_separators_falls_back_to_general(self) -> None:
        assert ingestion._clamp_category_path("///") == "general"

    def test_whitespace_only_path_falls_back_to_general(self) -> None:
        # A blank folder name would create an unnamed folder in the user's
        # memory tree and get fed back into the extraction prompt.
        assert ingestion._clamp_category_path("   ") == "general"
        assert ingestion._clamp_category_path(" / / ") == "general"

    def test_segment_whitespace_is_trimmed(self) -> None:
        assert ingestion._clamp_category_path(" work / gaia ") == "work/gaia"


class TestFormatFolderTree:
    def test_renders_one_line_per_folder_with_counts(self) -> None:
        assert ingestion._format_folder_tree([("work", 3), ("work/gaia", 1)]) == (
            "- work (3)\n- work/gaia (1)"
        )

    def test_empty_tree_renders_empty_string(self) -> None:
        assert ingestion._format_folder_tree([]) == ""


class TestElapsedMs:
    def test_returns_a_nonnegative_integer(self) -> None:
        import time

        elapsed = ingestion._elapsed_ms(time.perf_counter())
        assert isinstance(elapsed, int)
        assert elapsed >= 0

    def test_measures_from_the_given_reading(self) -> None:
        import time

        assert ingestion._elapsed_ms(time.perf_counter() - 0.5) >= 400

    def test_exact_value_from_a_patched_clock(self) -> None:
        with patch.object(ingestion.time, "perf_counter", return_value=123.456):
            elapsed = ingestion._elapsed_ms(23.456)
        assert elapsed == 100_000
        assert type(elapsed) is int


class TestEnforceFreeCap:
    def test_admits_only_the_first_remaining_growth_facts(self) -> None:
        items = [make_reconciled(make_fact(f"f{index}")) for index in range(4)]
        kept, dropped = ingestion._enforce_free_cap(items, remaining=2)
        assert dropped == 2
        assert [item.fact.content for item in kept] == ["f0", "f1"]

    def test_non_growth_outcomes_pass_through_untouched(self) -> None:
        items = [
            make_reconciled(make_fact("a")),
            make_reconciled(make_fact("b"), ReconcileOutcome.DUPLICATE),
            make_reconciled(make_fact("c"), ReconcileOutcome.UPDATES),
            make_reconciled(make_fact("d")),
        ]
        kept, dropped = ingestion._enforce_free_cap(items, remaining=1)
        assert dropped == 1
        assert [item.fact.content for item in kept] == ["a", "b", "c"]

    def test_extends_counts_against_the_quota(self) -> None:
        items = [
            make_reconciled(make_fact("a")),
            make_reconciled(make_fact("b"), ReconcileOutcome.EXTENDS),
        ]
        kept, dropped = ingestion._enforce_free_cap(items, remaining=1)
        assert dropped == 1
        assert [item.fact.content for item in kept] == ["a"]

    def test_zero_remaining_drops_every_growth_fact(self) -> None:
        items = [
            make_reconciled(make_fact("a")),
            make_reconciled(make_fact("b"), ReconcileOutcome.DUPLICATE),
            make_reconciled(make_fact("c")),
        ]
        kept, dropped = ingestion._enforce_free_cap(items, remaining=0)
        assert dropped == 2
        assert [item.fact.content for item in kept] == ["b"]

    def test_plenty_of_room_drops_nothing(self) -> None:
        items = [make_reconciled(make_fact(f"f{index}")) for index in range(3)]
        kept, dropped = ingestion._enforce_free_cap(items, remaining=10)
        assert dropped == 0
        assert len(kept) == 3


class TestFreeCapRemaining:
    async def test_paid_plan_is_uncapped_without_infra_lookups(
        self, boundaries: Boundaries
    ) -> None:
        remaining = await ingestion._free_cap_remaining(USER, growth=1)
        assert remaining is None
        boundaries.get_cached_live_count.assert_not_awaited()
        boundaries.count_live_memories.assert_not_awaited()
        boundaries.set_cached_live_count.assert_not_awaited()

    async def test_plan_lookup_failure_fails_open(self, boundaries: Boundaries) -> None:
        boundaries.get_cached_plan_type.side_effect = RuntimeError("boom")
        with patch.object(ingestion.log, "warning") as warn:
            remaining = await ingestion._free_cap_remaining(USER, growth=1)
        assert remaining is None
        warn.assert_called_once_with(
            "Memory cap plan lookup failed (failing open)",
            error="boom",
            error_type="RuntimeError",
        )
        boundaries.count_live_memories.assert_not_awaited()

    async def test_free_user_with_cached_room_returns_the_cached_remaining(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.get_cached_plan_type.return_value = PlanType.FREE
        boundaries.get_cached_live_count.return_value = 10
        remaining = await ingestion._free_cap_remaining(USER, growth=2)
        assert remaining == FREE_MEMORY_FACT_LIMIT - 10
        boundaries.get_cached_plan_type.assert_awaited_once_with(USER)
        boundaries.get_cached_live_count.assert_awaited_once_with(USER)
        boundaries.count_live_memories.assert_not_awaited()
        boundaries.set_cached_live_count.assert_not_awaited()

    async def test_cached_remaining_at_the_margin_boundary_is_still_trusted(
        self, boundaries: Boundaries
    ) -> None:
        # Exactly `growth + margin` left per the cache: the batch cannot cross
        # the cap, so the cache decides without consulting the COUNT.
        boundaries.get_cached_plan_type.return_value = PlanType.FREE
        cached = FREE_MEMORY_FACT_LIMIT - (2 + FREE_MEMORY_CAP_COUNT_SAFETY_MARGIN)
        boundaries.get_cached_live_count.return_value = cached
        remaining = await ingestion._free_cap_remaining(USER, growth=2)
        assert remaining == 2 + FREE_MEMORY_CAP_COUNT_SAFETY_MARGIN
        boundaries.count_live_memories.assert_not_awaited()

    async def test_cached_remaining_below_the_margin_falls_back_to_the_count(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.get_cached_plan_type.return_value = PlanType.FREE
        # 11 cached slots left — one below the growth(2) + margin(10) trust
        # threshold — so the authoritative COUNT must decide.
        boundaries.get_cached_live_count.return_value = 39
        boundaries.count_live_memories.return_value = 42
        remaining = await ingestion._free_cap_remaining(USER, growth=2)
        assert remaining == FREE_MEMORY_FACT_LIMIT - 42
        boundaries.count_live_memories.assert_awaited_once_with(USER)
        boundaries.set_cached_live_count.assert_awaited_once_with(USER, 42)

    async def test_cache_miss_falls_back_to_the_count(self, boundaries: Boundaries) -> None:
        boundaries.get_cached_plan_type.return_value = PlanType.FREE
        boundaries.get_cached_live_count.return_value = None
        boundaries.count_live_memories.return_value = 48
        remaining = await ingestion._free_cap_remaining(USER, growth=5)
        assert remaining == 2
        boundaries.count_live_memories.assert_awaited_once_with(USER)
        boundaries.set_cached_live_count.assert_awaited_once_with(USER, 48)

    async def test_remaining_is_never_negative(self, boundaries: Boundaries) -> None:
        boundaries.get_cached_plan_type.return_value = PlanType.FREE
        boundaries.get_cached_live_count.return_value = None
        boundaries.count_live_memories.return_value = 60
        remaining = await ingestion._free_cap_remaining(USER, growth=1)
        assert remaining == 0
        boundaries.set_cached_live_count.assert_awaited_once_with(USER, 60)

    async def test_at_or_over_cap_via_cache_falls_back_to_the_authoritative_count(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.get_cached_plan_type.return_value = PlanType.FREE
        boundaries.get_cached_live_count.return_value = 70
        boundaries.count_live_memories.return_value = 55
        remaining = await ingestion._free_cap_remaining(USER, growth=1)
        assert remaining == 0
        boundaries.count_live_memories.assert_awaited_once_with(USER)
        boundaries.set_cached_live_count.assert_awaited_once_with(USER, 55)


class TestBuildRecord:
    def test_maps_every_fact_field_onto_the_row(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 2, tzinfo=UTC)
        forget = datetime(2026, 6, 1, tzinfo=UTC)
        fact = make_fact(
            "sam moved to berlin",
            kind=MemoryKind.EXPERIENCE,
            category_path="life/moves",
            importance=0.9,
            occurred_start=start,
            occurred_end=end,
            forget_after=forget,
        )
        record = ingestion._build_record(
            fact, user_id=USER, source_type=MemorySourceType.EMAIL, source_id="msg-9"
        )
        assert record.user_id == USER
        assert record.kind == MemoryKind.EXPERIENCE.value
        assert record.content == "sam moved to berlin"
        assert record.category_path == "life/moves"
        assert record.importance == 0.9
        assert record.occurred_start == start
        assert record.occurred_end == end
        assert record.forget_after == forget
        assert record.source_type == MemorySourceType.EMAIL.value
        assert record.source_id == "msg-9"

    def test_category_path_is_clamped_on_the_row(self) -> None:
        record = ingestion._build_record(
            make_fact(category_path="a/b/c/d"),
            user_id=USER,
            source_type=MemorySourceType.CONVERSATION,
            source_id=None,
        )
        assert record.category_path == "a/b/c"

    def test_mentioned_at_is_left_to_the_column_default_when_absent(self) -> None:
        record = ingestion._build_record(
            make_fact(), user_id=USER, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert record.mentioned_at is None

    def test_mentioned_at_is_set_when_replaying_a_historical_session(self) -> None:
        replay = datetime(2020, 5, 4, tzinfo=UTC)
        record = ingestion._build_record(
            make_fact(),
            user_id=USER,
            source_type=MemorySourceType.MIGRATION,
            source_id=None,
            mentioned_at=replay,
        )
        assert record.mentioned_at == replay

    def test_lineage_fields_are_left_unset(self) -> None:
        record = ingestion._build_record(
            make_fact(), user_id=USER, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert record.parent_id is None
        assert record.relation_type is None


class TestStoreConversationChunks:
    async def test_turns_are_grouped_and_prefixed_with_their_role(
        self, boundaries: Boundaries
    ) -> None:
        await ingestion._store_conversation_chunks(
            USER,
            [
                {"role": "user", "content": "what is the plan"},
                {"role": "assistant", "content": "ship the memory pipeline"},
            ],
            source_id="conv-1",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert boundaries.chunk_documents == [
            "user: what is the plan\nassistant: ship the memory pipeline"
        ]

    async def test_turns_are_flushed_every_chunk_turn_limit(self, boundaries: Boundaries) -> None:
        messages = [{"role": "user", "content": f"turn {index}"} for index in range(9)]
        await ingestion._store_conversation_chunks(
            USER, messages, source_id="c", now=datetime(2026, 1, 1, tzinfo=UTC)
        )
        documents = boundaries.chunk_documents
        assert [len(doc.splitlines()) for doc in documents] == [
            TRANSCRIPT_CHUNK_TURNS,
            TRANSCRIPT_CHUNK_TURNS,
            1,
        ]

    async def test_message_without_a_role_defaults_to_user(self, boundaries: Boundaries) -> None:
        await ingestion._store_conversation_chunks(
            USER, [{"content": "no role"}], source_id="c", now=datetime(2026, 1, 1, tzinfo=UTC)
        )
        assert boundaries.chunk_documents == ["user: no role"]

    async def test_empty_content_is_skipped(self, boundaries: Boundaries) -> None:
        await ingestion._store_conversation_chunks(
            USER,
            [{"role": "user", "content": ""}, {"role": "user", "content": "real"}],
            source_id="c",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert boundaries.chunk_documents == ["user: real"]

    async def test_whitespace_only_content_is_skipped(self, boundaries: Boundaries) -> None:
        # A blank turn would otherwise cost an embedding and land in the
        # transcript store as a contentless "user:   " chunk.
        await ingestion._store_conversation_chunks(
            USER,
            [{"role": "user", "content": "   \n\t "}],
            source_id="c",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert boundaries.chunk_documents == []
        boundaries.upsert_conversation_chunks.assert_not_awaited()
        boundaries.embed_batch.assert_not_awaited()

    async def test_no_messages_stores_nothing(self, boundaries: Boundaries) -> None:
        await ingestion._store_conversation_chunks(
            USER, [], source_id="c", now=datetime(2026, 1, 1, tzinfo=UTC)
        )
        boundaries.upsert_conversation_chunks.assert_not_awaited()

    async def test_oversized_turn_is_split_into_overlapping_windows(
        self, boundaries: Boundaries
    ) -> None:
        body = "".join(f"item{index:04d} " for index in range(400))
        assert len(body) > TRANSCRIPT_CHUNK_MAX_CHARS
        await ingestion._store_conversation_chunks(
            USER,
            [{"role": "user", "content": body}],
            source_id="c",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        documents = boundaries.chunk_documents
        assert len(documents) > 1
        assert all(len(doc) <= TRANSCRIPT_CHUNK_MAX_CHARS for doc in documents)
        # No content is lost across the split, and consecutive windows overlap.
        assert documents[0].startswith("user: ")
        assert body[-20:] in documents[-1]
        step = TRANSCRIPT_CHUNK_MAX_CHARS - TRANSCRIPT_CHUNK_OVERLAP_CHARS
        assert documents[0][step:] == documents[1][: TRANSCRIPT_CHUNK_MAX_CHARS - step]

    async def test_oversized_turn_flushes_the_pending_group_first(
        self, boundaries: Boundaries
    ) -> None:
        await ingestion._store_conversation_chunks(
            USER,
            [
                {"role": "user", "content": "short one"},
                {"role": "assistant", "content": "x" * (TRANSCRIPT_CHUNK_MAX_CHARS + 50)},
            ],
            source_id="c",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        documents = boundaries.chunk_documents
        assert documents[0] == "user: short one"
        assert len(documents) > 1

    async def test_oversized_turn_does_not_swallow_later_turns(
        self, boundaries: Boundaries
    ) -> None:
        # An oversized turn must only split itself: the messages after it
        # still get chunked, not dropped.
        await ingestion._store_conversation_chunks(
            USER,
            [
                {"role": "user", "content": "x" * (TRANSCRIPT_CHUNK_MAX_CHARS + 50)},
                {"role": "user", "content": "after"},
            ],
            source_id="c",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        documents = boundaries.chunk_documents
        assert documents[-1] == "user: after"
        assert any(len(doc) <= TRANSCRIPT_CHUNK_MAX_CHARS for doc in documents[:-1])

    async def test_chunks_are_capped_per_session(self, boundaries: Boundaries) -> None:
        messages = [
            {"role": "user", "content": f"turn {index} " + "y" * 400} for index in range(400)
        ]
        await ingestion._store_conversation_chunks(
            USER, messages, source_id="c", now=datetime(2026, 1, 1, tzinfo=UTC)
        )
        assert len(boundaries.chunk_documents) == TRANSCRIPT_CHUNKS_PER_SESSION_CAP

    async def test_chunk_ids_and_metadata_are_derived_from_session_and_day(
        self, boundaries: Boundaries
    ) -> None:
        await ingestion._store_conversation_chunks(
            USER,
            [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}] * 3,
            source_id="conv-7",
            now=datetime(2026, 3, 5, 12, 0, tzinfo=UTC),
        )
        items = boundaries.upsert_conversation_chunks.await_args.args[0]
        assert [item["id"] for item in items] == [
            f"{USER}:conv-7:{index}" for index in range(len(items))
        ]
        assert all(item["metadata"] == {"user_id": USER, "date": "2026-03-05"} for item in items)

    async def test_missing_source_id_gets_a_random_session_key(
        self, boundaries: Boundaries
    ) -> None:
        await ingestion._store_conversation_chunks(
            USER,
            [{"role": "user", "content": "a"}],
            source_id=None,
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        chunk_id = boundaries.upsert_conversation_chunks.await_args.args[0][0]["id"]
        prefix, session_key, index = chunk_id.split(":")
        assert prefix == USER
        assert index == "0"
        assert len(session_key) == 12 and session_key != "None"

    async def test_each_chunk_is_paired_with_its_own_embedding(
        self, boundaries: Boundaries
    ) -> None:
        messages = [{"role": "user", "content": f"turn {index}"} for index in range(9)]
        await ingestion._store_conversation_chunks(
            USER, messages, source_id="c", now=datetime(2026, 1, 1, tzinfo=UTC)
        )
        items = boundaries.upsert_conversation_chunks.await_args.args[0]
        # The stub embedder returns [index, 0.5] per input, in order.
        assert [item["embedding"] for item in items] == [
            [float(index), 0.5] for index in range(len(items))
        ]

    async def test_message_without_a_content_key_is_skipped(self, boundaries: Boundaries) -> None:
        # A missing "content" key must be treated like empty content, not as
        # None (which would crash .strip()) or as a placeholder (which would
        # store a garbage chunk).
        await ingestion._store_conversation_chunks(
            USER,
            [{"role": "user"}, {"role": "user", "content": "real"}],
            source_id="c",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert boundaries.chunk_documents == ["user: real"]

    async def test_a_turn_of_exactly_the_maximum_length_is_not_split(
        self, boundaries: Boundaries
    ) -> None:
        # Splitting is strictly for turns LONGER than the cap; an exactly-at-
        # cap turn must stay whole.
        content = "a" * (TRANSCRIPT_CHUNK_MAX_CHARS - len("user: "))
        await ingestion._store_conversation_chunks(
            USER,
            [{"role": "user", "content": content}],
            source_id="c",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert boundaries.chunk_documents == [f"user: {content}"]

    async def test_turn_group_flushes_exactly_at_the_char_limit(
        self, boundaries: Boundaries
    ) -> None:
        # Two turns whose prefixed lengths sum to exactly the cap: the group
        # must flush at the second turn so a third turn starts a fresh chunk.
        first = "a" * 600
        second = "b" * (TRANSCRIPT_CHUNK_MAX_CHARS - len("user: ") * 2 - len(first))
        await ingestion._store_conversation_chunks(
            USER,
            [
                {"role": "user", "content": first},
                {"role": "user", "content": second},
                {"role": "user", "content": "c"},
            ],
            source_id="c",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert boundaries.chunk_documents == [
            f"user: {first}\nuser: {second}",
            "user: c",
        ]

    async def test_group_char_accumulation_is_reset_across_flushes(
        self, boundaries: Boundaries
    ) -> None:
        # The accumulated char count must start over after each flush: a second
        # group that independently crosses the cap must not flush one turn late
        # (or early) because the first group's length leaked into it.
        first = "a" * (TRANSCRIPT_CHUNK_MAX_CHARS - len("user: "))
        second = "b" * (TRANSCRIPT_CHUNK_MAX_CHARS - len("user: ") - 1)
        third = "c" * 4
        await ingestion._store_conversation_chunks(
            USER,
            [
                {"role": "user", "content": first},
                {"role": "user", "content": second},
                {"role": "user", "content": third},
            ],
            source_id="c",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert boundaries.chunk_documents == [
            f"user: {first}",
            f"user: {second}\nuser: {third}",
        ]

    async def test_group_flush_when_a_later_turn_crosses_the_char_limit(
        self, boundaries: Boundaries
    ) -> None:
        # A group that crosses the cap in the middle must flush there, not
        # swallow the turns after it.
        first = "a" * (TRANSCRIPT_CHUNK_MAX_CHARS - len("user: ") - 1)
        second = "b" * 4
        third = "c" * 4
        await ingestion._store_conversation_chunks(
            USER,
            [
                {"role": "user", "content": first},
                {"role": "user", "content": second},
                {"role": "user", "content": third},
            ],
            source_id="c",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert boundaries.chunk_documents == [
            f"user: {first}\nuser: {second}",
            "user: cccc",
        ]


class TestAppendEpisodeEntries:
    async def test_no_entries_writes_nothing(self, boundaries: Boundaries) -> None:
        count = await ingestion._append_episode_entries(
            USER, [], source_type=MemorySourceType.CONVERSATION, now=datetime.now(UTC)
        )
        assert count == 0
        boundaries.append_episode_entries.assert_not_awaited()

    async def test_entries_are_stamped_with_the_ingestion_time_and_day(
        self, boundaries: Boundaries
    ) -> None:
        count = await ingestion._append_episode_entries(
            USER,
            ["drafted the email", "booked the dentist"],
            source_type=MemorySourceType.TOOL,
            now=datetime(2026, 3, 5, 23, 47, tzinfo=UTC),
        )
        assert count == 2
        user_id, day, entries = boundaries.append_episode_entries.await_args.args
        assert user_id == USER
        assert day == date_type(2026, 3, 5)
        assert entries == [
            {"time": "23:47", "text": "drafted the email", "source": "tool"},
            {"time": "23:47", "text": "booked the dentist", "source": "tool"},
        ]


class TestSummarizeEpisode:
    async def test_missing_episode_is_a_noop(self, boundaries: Boundaries) -> None:
        boundaries.get_episode.return_value = None
        await summarize_episode(USER, date_type(2026, 1, 1))
        boundaries.get_episode.assert_awaited_once_with(USER, date_type(2026, 1, 1))
        boundaries.summarize_episode_entries.assert_not_awaited()
        boundaries.set_episode_summary.assert_not_awaited()

    async def test_already_summarized_episode_is_not_resummarized(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.get_episode.return_value = make_episode(
            summary="done", entries=[{"time": "10:00", "text": "a thing"}]
        )
        await summarize_episode(USER, date_type(2026, 1, 1))
        boundaries.summarize_episode_entries.assert_not_awaited()

    async def test_episode_without_entries_is_not_summarized(self, boundaries: Boundaries) -> None:
        boundaries.get_episode.return_value = make_episode(summary=None, entries=[])
        await summarize_episode(USER, date_type(2026, 1, 1))
        boundaries.summarize_episode_entries.assert_not_awaited()

    async def test_empty_string_summary_is_treated_as_missing(self, boundaries: Boundaries) -> None:
        boundaries.get_episode.return_value = make_episode(
            summary="", entries=[{"time": "10:00", "text": "a thing"}]
        )
        await summarize_episode(USER, date_type(2026, 1, 1))
        assert boundaries.set_episode_summary.await_count == 1

    async def test_summary_is_persisted_and_embedded(self, boundaries: Boundaries) -> None:
        boundaries.get_episode.return_value = make_episode(
            entries=[{"time": "09:00", "text": "shipped it"}, {"time": "18:00", "text": "rested"}]
        )
        boundaries.summarize_episode_entries.return_value = "A productive day."
        await summarize_episode(USER, date_type(2026, 1, 1))

        assert boundaries.summarize_episode_entries.await_args.args[0] == [
            "09:00 shipped it",
            "18:00 rested",
        ]
        assert boundaries.summarize_episode_entries.await_args.kwargs["user_id"] == USER
        assert boundaries.set_episode_summary.await_args.args == (
            USER,
            date_type(2026, 1, 1),
            "A productive day.",
        )
        item = boundaries.upsert_episode.await_args.args[0]
        assert item["id"] == f"{USER}:2026-01-01"
        assert item["document"] == "A productive day."
        assert item["embedding"] == [0.9, 0.9]
        assert item["metadata"] == {"user_id": USER, "date": "2026-01-01"}
        assert boundaries.embed_query.await_args.args == ("A productive day.",)

    async def test_failed_summarization_writes_nothing(self, boundaries: Boundaries) -> None:
        boundaries.get_episode.return_value = make_episode(
            entries=[{"time": "09:00", "text": "shipped it"}]
        )
        boundaries.summarize_episode_entries.return_value = None
        await summarize_episode(USER, date_type(2026, 1, 1))
        boundaries.set_episode_summary.assert_not_awaited()
        boundaries.upsert_episode.assert_not_awaited()
        boundaries.embed_query.assert_not_awaited()

    async def test_entries_missing_keys_do_not_crash_the_summary(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.get_episode.return_value = make_episode(entries=[{}, {"text": "no time"}])
        await summarize_episode(USER, date_type(2026, 1, 1))
        assert boundaries.summarize_episode_entries.await_args.args[0] == [" ", " no time"]


class TestSummarizeRolledOverDays:
    async def test_every_unsummarized_day_is_summarized(self, boundaries: Boundaries) -> None:
        days = [date_type(2026, 1, 1), date_type(2026, 1, 2)]
        boundaries.get_unsummarized_episode_dates.return_value = days
        boundaries.get_episode.side_effect = [
            make_episode(entries=[{"time": "10:00", "text": "a"}]),
            make_episode(entries=[{"time": "10:00", "text": "b"}]),
        ]
        await ingestion._summarize_rolled_over_days(USER, today=date_type(2026, 1, 3))
        assert boundaries.set_episode_summary.await_count == 2
        assert [call.args[1] for call in boundaries.set_episode_summary.await_args_list] == days
        assert all(call.args[0] == USER for call in boundaries.set_episode_summary.await_args_list)
        boundaries.get_unsummarized_episode_dates.assert_awaited_once_with(
            USER, date_type(2026, 1, 3)
        )

    async def test_nothing_to_roll_over_is_a_noop(self, boundaries: Boundaries) -> None:
        boundaries.get_unsummarized_episode_dates.return_value = []
        await ingestion._summarize_rolled_over_days(USER, today=date_type(2026, 1, 3))
        boundaries.set_episode_summary.assert_not_awaited()


class TestApplyReconciled:
    async def test_new_facts_are_inserted_and_counted(self, boundaries: Boundaries) -> None:
        reconciled = [
            make_reconciled(make_fact("a"), embedding=[1.0]),
            make_reconciled(make_fact("b"), embedding=[2.0]),
        ]
        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id="s1"
        )
        assert (applied.new, applied.updated, applied.extended, applied.duplicates) == (2, 0, 0, 0)
        assert [record.content for record in boundaries.inserted_records] == ["a", "b"]
        assert all(record.user_id == USER for record in boundaries.inserted_records)
        assert all(record.source_id == "s1" for record in boundaries.inserted_records)

    async def test_duplicates_are_counted_and_never_written(self, boundaries: Boundaries) -> None:
        reconciled = [
            make_reconciled(make_fact("dupe"), ReconcileOutcome.DUPLICATE, target_memory_id="t1")
        ]
        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert applied.duplicates == 1
        assert applied.new == 0
        assert boundaries.inserted_records == []
        assert applied.inserted == []
        assert boundaries.vector_items == []

    async def test_extends_links_to_its_parent_without_bumping_the_version(
        self, boundaries: Boundaries
    ) -> None:
        parent = make_row(content="sam drinks tea")
        boundaries.get_memories_by_ids.return_value = [parent]
        reconciled = [
            make_reconciled(
                make_fact("sam drinks matcha"),
                ReconcileOutcome.EXTENDS,
                target_memory_id=str(parent.id),
            )
        ]
        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert applied.extended == 1
        assert applied.new == 0
        boundaries.get_memories_by_ids.assert_awaited_once_with(USER, [str(parent.id)])
        record = boundaries.inserted_records[0]
        assert record.parent_id == parent.id
        assert record.relation_type == MemoryRelationType.EXTENDS.value
        # EXTENDS coexists with its parent: no supersession, no version bump.
        assert record.root_id is None
        boundaries.set_memory_flags.assert_not_awaited()

    async def test_extends_with_a_vanished_parent_degrades_to_a_plain_new(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.get_memories_by_ids.return_value = []
        reconciled = [
            make_reconciled(make_fact("orphan"), ReconcileOutcome.EXTENDS, target_memory_id="gone")
        ]
        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert (applied.new, applied.extended) == (1, 0)
        record = boundaries.inserted_records[0]
        assert record.parent_id is None
        assert record.relation_type is None

    async def test_extends_without_a_target_id_is_treated_as_new(
        self, boundaries: Boundaries
    ) -> None:
        reconciled = [
            make_reconciled(make_fact("no target"), ReconcileOutcome.EXTENDS, target_memory_id=None)
        ]
        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert (applied.new, applied.extended) == (1, 0)
        boundaries.get_memories_by_ids.assert_awaited_once_with(USER, [])

    async def test_updates_supersedes_the_target_and_retires_its_vector(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.supersede_memory.return_value = make_row()
        reconciled = [
            make_reconciled(
                make_fact("sam moved to berlin"),
                ReconcileOutcome.UPDATES,
                target_memory_id="old-1",
            )
        ]
        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert (applied.updated, applied.new) == (1, 0)
        target_id, user_id, record, relation = boundaries.supersede_memory.await_args.args
        assert (target_id, user_id, relation) == ("old-1", USER, MemoryRelationType.UPDATES)
        assert record.content == "sam moved to berlin"
        boundaries.set_memory_flags.assert_awaited_once_with("old-1", is_latest=False)

    async def test_updates_whose_target_vanished_is_stored_as_new(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.supersede_memory.return_value = None
        reconciled = [
            make_reconciled(make_fact("racy"), ReconcileOutcome.UPDATES, target_memory_id="old-1")
        ]
        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert (applied.new, applied.updated) == (1, 0)
        # The row must still be persisted, and the vanished target's vector
        # must not be retired.
        assert [record.content for record in boundaries.inserted_records] == ["racy"]
        boundaries.set_memory_flags.assert_not_awaited()

    async def test_updates_without_a_target_id_is_ignored(self, boundaries: Boundaries) -> None:
        reconciled = [
            make_reconciled(make_fact("x"), ReconcileOutcome.UPDATES, target_memory_id=None)
        ]
        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert (applied.new, applied.updated) == (0, 0)
        boundaries.supersede_memory.assert_not_awaited()
        assert boundaries.inserted_records == []

    async def test_vectors_carry_the_row_id_content_and_latest_flags(
        self, boundaries: Boundaries
    ) -> None:
        reconciled = [make_reconciled(make_fact("a", category_path="work/x"), embedding=[7.0])]
        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        record = applied.inserted[0][0]
        item = boundaries.vector_items[0]
        assert item["id"] == str(record.id)
        assert item["id"] != "None"
        assert item["document"] == "a"
        assert item["embedding"] == [7.0]
        assert item["metadata"] == {
            "user_id": USER,
            "kind": MemoryKind.FACT.value,
            "category_path": "work/x",
            "is_latest": True,
            "is_forgotten": False,
        }

    async def test_each_row_gets_its_own_vector_id(self, boundaries: Boundaries) -> None:
        reconciled = [
            make_reconciled(make_fact("a"), embedding=[1.0]),
            make_reconciled(make_fact("b"), embedding=[2.0]),
        ]
        await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        ids = [item["id"] for item in boundaries.vector_items]
        assert len(set(ids)) == 2

    async def test_mentioned_at_is_propagated_to_every_row(self, boundaries: Boundaries) -> None:
        replay = datetime(2019, 7, 4, tzinfo=UTC)
        boundaries.supersede_memory.return_value = make_row()
        reconciled = [
            make_reconciled(make_fact("a")),
            make_reconciled(make_fact("b"), ReconcileOutcome.UPDATES, target_memory_id="t"),
        ]
        applied = await ingestion._apply_reconciled(
            USER,
            reconciled,
            source_type=MemorySourceType.MIGRATION,
            source_id="s9",
            mentioned_at=replay,
        )
        assert [record.mentioned_at for record, _ in applied.inserted] == [replay, replay]
        assert all(record.user_id == USER for record, _ in applied.inserted)
        assert all(record.source_id == "s9" for record, _ in applied.inserted)

    async def test_two_extends_each_count_toward_the_total(self, boundaries: Boundaries) -> None:
        parent_a, parent_b = make_row(), make_row()
        boundaries.get_memories_by_ids.return_value = [parent_a, parent_b]
        reconciled = [
            make_reconciled(
                make_fact("a"),
                ReconcileOutcome.EXTENDS,
                target_memory_id=str(parent_a.id),
            ),
            make_reconciled(
                make_fact("b"),
                ReconcileOutcome.EXTENDS,
                target_memory_id=str(parent_b.id),
            ),
        ]
        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert (applied.new, applied.extended) == (0, 2)

    async def test_two_duplicates_each_count_toward_the_total(self, boundaries: Boundaries) -> None:
        reconciled = [
            make_reconciled(make_fact("d1"), ReconcileOutcome.DUPLICATE, target_memory_id="t1"),
            make_reconciled(make_fact("d2"), ReconcileOutcome.DUPLICATE, target_memory_id="t2"),
        ]
        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert (applied.duplicates, applied.new, applied.updated, applied.extended) == (2, 0, 0, 0)
        assert boundaries.inserted_records == []
        boundaries.adjust_live_count.assert_awaited_once_with(USER, 0)

    async def test_two_updates_each_count_toward_the_total(self, boundaries: Boundaries) -> None:
        boundaries.supersede_memory.return_value = make_row()
        reconciled = [
            make_reconciled(make_fact("u1"), ReconcileOutcome.UPDATES, target_memory_id="old-1"),
            make_reconciled(make_fact("u2"), ReconcileOutcome.UPDATES, target_memory_id="old-2"),
        ]
        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert (applied.updated, applied.new, applied.extended, applied.duplicates) == (2, 0, 0, 0)
        assert [call.args[0] for call in boundaries.supersede_memory.await_args_list] == [
            "old-1",
            "old-2",
        ]
        assert boundaries.set_memory_flags.await_count == 2
        boundaries.adjust_live_count.assert_awaited_once_with(USER, 0)

    async def test_two_vanished_updates_each_count_toward_the_new_total(
        self, boundaries: Boundaries
    ) -> None:
        # Both targets vanish between reconcile and apply: each superseded fact
        # lands as a plain NEW, so the new counter must accumulate.
        boundaries.supersede_memory.return_value = None
        reconciled = [
            make_reconciled(make_fact("v1"), ReconcileOutcome.UPDATES, target_memory_id="gone-1"),
            make_reconciled(make_fact("v2"), ReconcileOutcome.UPDATES, target_memory_id="gone-2"),
        ]
        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert (applied.new, applied.updated) == (2, 0)
        assert [record.content for record in boundaries.inserted_records] == ["v1", "v2"]
        boundaries.set_memory_flags.assert_not_awaited()
        boundaries.adjust_live_count.assert_awaited_once_with(USER, 2)

    async def test_empty_reconciliation_writes_nothing(self, boundaries: Boundaries) -> None:
        applied = await ingestion._apply_reconciled(
            USER, [], source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert applied == ingestion._ApplyResult(
            inserted=[], duplicates=0, new=0, updated=0, extended=0
        )
        assert boundaries.vector_items == []
        boundaries.adjust_live_count.assert_awaited_once_with(USER, 0)

    async def test_mixed_outcomes_are_each_counted_once(self, boundaries: Boundaries) -> None:
        parent = make_row()
        boundaries.get_memories_by_ids.return_value = [parent]
        boundaries.supersede_memory.return_value = make_row()
        reconciled = [
            make_reconciled(make_fact("new one"), embedding=[1.0]),
            make_reconciled(
                make_fact("extends one"),
                ReconcileOutcome.EXTENDS,
                embedding=[2.0],
                target_memory_id=str(parent.id),
            ),
            make_reconciled(
                make_fact("updates one"),
                ReconcileOutcome.UPDATES,
                embedding=[3.0],
                target_memory_id="old",
            ),
            make_reconciled(
                make_fact("dupe one"),
                ReconcileOutcome.DUPLICATE,
                embedding=[4.0],
                target_memory_id="old",
            ),
        ]
        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert (applied.new, applied.extended, applied.updated, applied.duplicates) == (1, 1, 1, 1)
        assert len(applied.inserted) == 3
        assert len(boundaries.vector_items) == 3
        # NEW + EXTENDS grow the live set by exactly 2; UPDATES and DUPLICATEs net zero.
        boundaries.adjust_live_count.assert_awaited_once_with(USER, 2)


class TestApplyGraph:
    async def test_no_entities_skips_the_graph_entirely(self, boundaries: Boundaries) -> None:
        reconciled = [make_reconciled(make_fact("no entities"))]
        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert (applied.entities_linked, applied.edges_added) == (0, 0)
        boundaries.upsert_entities.assert_not_awaited()
        boundaries.link_entities.assert_not_awaited()

    async def test_entities_are_linked_to_their_memory_row(self, boundaries: Boundaries) -> None:
        sam, berlin = uuid.uuid4(), uuid.uuid4()
        boundaries.upsert_entities.return_value = {"sam carter": sam, "berlin": berlin}
        fact = make_fact(
            "sam lives in berlin",
            entities=[
                ExtractedEntity(name="Sam Carter", entity_type="person"),
                ExtractedEntity(name="Berlin", entity_type="place"),
            ],
        )
        applied = await ingestion._apply_reconciled(
            USER,
            [make_reconciled(fact)],
            source_type=MemorySourceType.CONVERSATION,
            source_id=None,
        )
        assert applied.entities_linked == 2
        record = applied.inserted[0][0]
        linked_record_id, entity_ids = boundaries.link_entities.await_args.args
        assert linked_record_id == record.id
        assert set(entity_ids) == {sam, berlin}

    async def test_entity_names_are_matched_case_and_whitespace_insensitively(
        self, boundaries: Boundaries
    ) -> None:
        sam = uuid.uuid4()
        boundaries.upsert_entities.return_value = {"sam carter": sam}
        fact = make_fact(
            "x", entities=[ExtractedEntity(name="  SAM CARTER  ", entity_type="person")]
        )
        applied = await ingestion._apply_reconciled(
            USER,
            [make_reconciled(fact)],
            source_type=MemorySourceType.CONVERSATION,
            source_id=None,
        )
        assert applied.entities_linked == 1
        assert boundaries.link_entities.await_args.args[1] == [sam]

    async def test_entity_the_store_did_not_resolve_is_skipped(
        self, boundaries: Boundaries
    ) -> None:
        sam = uuid.uuid4()
        boundaries.upsert_entities.return_value = {"sam carter": sam}
        fact = make_fact(
            "x",
            entities=[
                ExtractedEntity(name="Sam Carter", entity_type="person"),
                ExtractedEntity(name="Unresolvable", entity_type="person"),
            ],
        )
        applied = await ingestion._apply_reconciled(
            USER,
            [make_reconciled(fact)],
            source_type=MemorySourceType.CONVERSATION,
            source_id=None,
        )
        assert applied.entities_linked == 1

    async def test_edges_between_known_entities_are_inserted(self, boundaries: Boundaries) -> None:
        sam, berlin = uuid.uuid4(), uuid.uuid4()
        boundaries.upsert_entities.return_value = {"sam carter": sam, "berlin": berlin}
        boundaries.insert_edges.return_value = 1
        fact = make_fact(
            "sam lives in berlin",
            entities=[
                ExtractedEntity(name="Sam Carter", entity_type="person"),
                ExtractedEntity(name="Berlin", entity_type="place"),
            ],
            edges=[ExtractedEdge(source="Sam Carter", relationship="lives_in", target="Berlin")],
        )
        applied = await ingestion._apply_reconciled(
            USER,
            [make_reconciled(fact)],
            source_type=MemorySourceType.CONVERSATION,
            source_id=None,
        )
        assert applied.edges_added == 1
        user_id, edges, record_id = boundaries.insert_edges.await_args.args
        assert user_id == USER
        assert edges == [(sam, "lives_in", berlin)]
        assert record_id == applied.inserted[0][0].id

    async def test_edge_referencing_an_unknown_entity_is_dropped(
        self, boundaries: Boundaries
    ) -> None:
        sam = uuid.uuid4()
        boundaries.upsert_entities.return_value = {"sam carter": sam}
        fact = make_fact(
            "x",
            entities=[ExtractedEntity(name="Sam Carter", entity_type="person")],
            edges=[ExtractedEdge(source="Sam Carter", relationship="knows", target="Nobody")],
        )
        await ingestion._apply_reconciled(
            USER,
            [make_reconciled(fact)],
            source_type=MemorySourceType.CONVERSATION,
            source_id=None,
        )
        assert boundaries.insert_edges.await_args.args[1] == []

    async def test_entity_names_and_types_are_forwarded_to_the_store(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.upsert_entities.return_value = {}
        fact = make_fact(
            "x",
            entities=[
                ExtractedEntity(name="Sam", entity_type="person"),
                ExtractedEntity(name="Acme", entity_type="organization"),
            ],
        )
        await ingestion._apply_reconciled(
            USER,
            [make_reconciled(fact)],
            source_type=MemorySourceType.CONVERSATION,
            source_id=None,
        )
        user_id, names_types = boundaries.upsert_entities.await_args.args
        assert user_id == USER
        assert names_types == [("Sam", "person"), ("Acme", "organization")]

    async def test_counts_accumulate_across_multiple_facts(self, boundaries: Boundaries) -> None:
        sam, berlin, acme = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        boundaries.upsert_entities.return_value = {
            "sam carter": sam,
            "berlin": berlin,
            "acme": acme,
        }
        # One edge for the first fact; the edge-less second fact contributes 0.
        boundaries.insert_edges.side_effect = [1, 0]
        with_edge = make_fact(
            "a",
            entities=[
                ExtractedEntity(name="Sam Carter", entity_type="person"),
                ExtractedEntity(name="Berlin", entity_type="place"),
            ],
            edges=[ExtractedEdge(source="Sam Carter", relationship="lives_in", target="Berlin")],
        )
        edge_less = make_fact(
            "b", entities=[ExtractedEntity(name="Acme", entity_type="organization")]
        )
        applied = await ingestion._apply_reconciled(
            USER,
            [
                make_reconciled(with_edge, embedding=[1.0]),
                make_reconciled(edge_less, embedding=[2.0]),
            ],
            source_type=MemorySourceType.CONVERSATION,
            source_id=None,
        )
        assert applied.entities_linked == 3
        assert applied.edges_added == 1
        assert boundaries.link_entities.await_count == 2
        assert boundaries.insert_edges.await_count == 2
        # The edge-less fact still asks for its (empty) edge list per record.
        assert boundaries.insert_edges.await_args_list[1].args[1] == []


class TestSchedulePostIngest:
    async def test_projection_sync_always_runs(self, boundaries: Boundaries) -> None:
        await ingestion._schedule_post_ingest(USER, inserted_facts=[], agenda_updates=[])
        boundaries.schedule_vfs_sync.assert_called_once_with(USER)

    async def test_no_touched_documents_skips_consolidation(self, boundaries: Boundaries) -> None:
        await ingestion._schedule_post_ingest(USER, inserted_facts=[], agenda_updates=[])
        boundaries.schedule_consolidation.assert_not_awaited()

    async def test_agenda_updates_alone_schedule_the_agenda_document(
        self, boundaries: Boundaries
    ) -> None:
        await ingestion._schedule_post_ingest(
            USER, inserted_facts=[], agenda_updates=["owes the user a draft"]
        )
        user_id, doc_types = boundaries.schedule_consolidation.await_args.args
        assert user_id == USER
        assert MemoryDocType.AGENDA_MD in doc_types
        assert boundaries.schedule_consolidation.await_args.kwargs["agenda_updates"] == [
            "owes the user a draft"
        ]

    async def test_experience_facts_schedule_the_insights_document(
        self, boundaries: Boundaries
    ) -> None:
        await ingestion._schedule_post_ingest(
            USER,
            inserted_facts=[make_fact("went to berlin", kind=MemoryKind.EXPERIENCE)],
            agenda_updates=[],
        )
        doc_types = boundaries.schedule_consolidation.await_args.args[1]
        assert MemoryDocType.INSIGHTS_MD in doc_types


class TestBuildSingleFact:
    async def test_explicit_folder_skips_the_categorize_call(self, boundaries: Boundaries) -> None:
        fact = await ingestion._build_single_fact(
            USER, "remember this", "work/gaia", datetime.now(UTC)
        )
        assert fact.category_path == "work/gaia"
        assert fact.kind is MemoryKind.FACT
        assert fact.importance == DEFAULT_MEMORY_IMPORTANCE
        boundaries.categorize_fact.assert_not_awaited()
        boundaries.get_folder_tree.assert_not_awaited()

    async def test_explicit_folder_produces_a_plain_fact_with_defaults(
        self, boundaries: Boundaries
    ) -> None:
        fact = await ingestion._build_single_fact(
            USER, "remember the gate code", "work/gaia", datetime(2026, 1, 1, tzinfo=UTC)
        )
        assert fact.content == "remember the gate code"
        assert fact.kind is MemoryKind.FACT
        assert fact.category_path == "work/gaia"
        assert fact.importance == DEFAULT_MEMORY_IMPORTANCE
        assert fact.entities == []
        assert fact.edges == []
        assert fact.occurred_start is None
        assert fact.occurred_end is None
        assert fact.forget_after is None

    async def test_missing_folder_uses_the_categorizer_verdict(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.get_folder_tree.return_value = [("work", 2)]
        boundaries.categorize_fact.return_value = FactCategorization(
            category_path="work/gaia",
            kind=MemoryKind.EXPERIENCE,
            importance=0.8,
            entities=[ExtractedEntity(name="Sam", entity_type="person")],
            edges=[],
        )
        fact = await ingestion._build_single_fact(USER, "shipped it", None, datetime.now(UTC))
        assert fact.category_path == "work/gaia"
        assert fact.kind is MemoryKind.EXPERIENCE
        assert fact.importance == 0.8
        assert [entity.name for entity in fact.entities] == ["Sam"]
        boundaries.get_folder_tree.assert_awaited_once_with(USER)
        assert boundaries.categorize_fact.await_args.kwargs["folder_tree"] == "- work (2)"

    async def test_categorizer_verdict_edges_are_propagated(self, boundaries: Boundaries) -> None:
        boundaries.get_folder_tree.return_value = [("work", 2)]
        boundaries.categorize_fact.return_value = FactCategorization(
            category_path="work/gaia",
            kind=MemoryKind.EXPERIENCE,
            importance=0.8,
            entities=[ExtractedEntity(name="Sam", entity_type="person")],
            edges=[ExtractedEdge(source="Sam", relationship="visited", target="Berlin")],
        )
        fact = await ingestion._build_single_fact(USER, "shipped it", None, datetime.now(UTC))
        assert fact.edges == [ExtractedEdge(source="Sam", relationship="visited", target="Berlin")]

    async def test_categorizer_receives_the_content_and_context_exactly(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.get_folder_tree.return_value = [("life", 1)]
        boundaries.categorize_fact.return_value = None
        now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        await ingestion._build_single_fact(USER, "x", None, now)
        boundaries.get_folder_tree.assert_awaited_once_with(USER)
        assert boundaries.categorize_fact.await_args.args == ("x",)
        assert boundaries.categorize_fact.await_args.kwargs == {
            "user_id": USER,
            "folder_tree": "- life (1)",
            "current_date": now,
        }

    async def test_failed_categorization_falls_back_to_the_general_folder(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.categorize_fact.return_value = None
        fact = await ingestion._build_single_fact(USER, "shipped it", None, datetime.now(UTC))
        assert fact.category_path == "general"
        assert fact.kind is MemoryKind.FACT
        assert fact.importance == DEFAULT_MEMORY_IMPORTANCE


class TestRetainSingle:
    async def test_stores_an_explicit_fact_and_reports_the_outcome(
        self, boundaries: Boundaries
    ) -> None:
        fact = make_fact("sam prefers matcha", category_path="preferences")
        boundaries.reconcile.return_value = [make_reconciled(fact)]
        entry = MagicMock()
        with patch.object(ingestion, "row_to_entry", return_value=entry) as row_to_entry:
            retained = await retain_single(
                USER,
                "sam prefers matcha",
                category_path="preferences",
                source_type=MemorySourceType.MANUAL,
            )
        assert retained.outcome is ReconcileOutcome.NEW
        assert retained.entry is entry
        assert [record.content for record in boundaries.inserted_records] == ["sam prefers matcha"]
        assert boundaries.inserted_records[0].source_type == MemorySourceType.MANUAL.value
        assert boundaries.inserted_records[0].user_id == USER
        assert row_to_entry.call_args.args[0] is boundaries.inserted_records[0]
        boundaries.categorize_fact.assert_not_awaited()

    async def test_fact_is_embedded_and_reconciled_verbatim(self, boundaries: Boundaries) -> None:
        fact = make_fact("sam prefers matcha")
        boundaries.reconcile.return_value = [make_reconciled(fact)]
        with patch.object(ingestion, "row_to_entry", return_value=MagicMock()):
            await retain_single(
                USER,
                "sam prefers matcha",
                category_path="preferences",
                source_type=MemorySourceType.MANUAL,
            )
        assert boundaries.embed_batch.await_args.args == (["sam prefers matcha"],)
        user_id, reconcile_facts, embeddings = boundaries.reconcile.await_args.args
        assert user_id == USER
        assert reconcile_facts == [fact]
        assert embeddings == [[0.0, 0.5]]

    async def test_extraction_is_skipped_entirely(self, boundaries: Boundaries) -> None:
        fact = make_fact("x")
        boundaries.reconcile.return_value = [make_reconciled(fact)]
        with patch.object(ingestion, "row_to_entry", return_value=MagicMock()):
            await retain_single(
                USER, "x", category_path="general", source_type=MemorySourceType.TOOL
            )
        boundaries.extract_memories.assert_not_awaited()

    async def test_duplicate_surfaces_the_memory_it_collapsed_into(
        self, boundaries: Boundaries
    ) -> None:
        existing = make_row(content="sam prefers matcha")
        boundaries.get_memory.return_value = existing
        fact = make_fact("sam prefers matcha")
        boundaries.reconcile.return_value = [
            make_reconciled(fact, ReconcileOutcome.DUPLICATE, target_memory_id="target-1")
        ]
        with patch.object(ingestion, "row_to_entry", return_value=MagicMock()) as row_to_entry:
            retained = await retain_single(
                USER, "sam prefers matcha", source_type=MemorySourceType.MANUAL
            )
        assert retained.outcome is ReconcileOutcome.DUPLICATE
        boundaries.get_memory.assert_awaited_once_with("target-1", USER)
        assert row_to_entry.call_args.args[0] is existing
        assert boundaries.inserted_records == []

    async def test_duplicate_whose_target_disappeared_raises(self, boundaries: Boundaries) -> None:
        boundaries.get_memory.return_value = None
        boundaries.reconcile.return_value = [
            make_reconciled(make_fact("x"), ReconcileOutcome.DUPLICATE, target_memory_id="gone")
        ]
        with pytest.raises(
            ValueError, match=r"^Memory was deduplicated but its target no longer exists$"
        ):
            await retain_single(USER, "x", source_type=MemorySourceType.MANUAL)

    async def test_duplicate_without_a_target_id_raises(self, boundaries: Boundaries) -> None:
        boundaries.reconcile.return_value = [
            make_reconciled(make_fact("x"), ReconcileOutcome.DUPLICATE, target_memory_id=None)
        ]
        with pytest.raises(
            ValueError, match=r"^Memory was deduplicated but its target no longer exists$"
        ):
            await retain_single(USER, "x", source_type=MemorySourceType.MANUAL)
        boundaries.get_memory.assert_not_awaited()

    async def test_reconciler_returning_no_verdict_raises_a_clear_error(
        self, boundaries: Boundaries
    ) -> None:
        # The reconcile LLM can return fewer decisions than facts, which drops
        # the fact entirely. The user-facing add-memory path must not surface
        # that as a bare IndexError.
        boundaries.reconcile.return_value = []
        with pytest.raises(
            ValueError,
            match=r"^Memory could not be reconciled against existing memories$",
        ):
            await retain_single(USER, "x", source_type=MemorySourceType.MANUAL)

    async def test_follow_ups_are_scheduled_for_the_stored_fact(
        self, boundaries: Boundaries
    ) -> None:
        fact = make_fact("went to berlin", kind=MemoryKind.EXPERIENCE)
        boundaries.reconcile.return_value = [make_reconciled(fact)]
        with patch.object(ingestion, "row_to_entry", return_value=MagicMock()):
            await retain_single(
                USER, "went to berlin", category_path="life", source_type=MemorySourceType.MANUAL
            )
        boundaries.invalidate_caches.assert_awaited_once_with(USER)
        boundaries.schedule_vfs_sync.assert_called_once_with(USER)
        assert MemoryDocType.INSIGHTS_MD in boundaries.schedule_consolidation.await_args.args[1]
        assert boundaries.schedule_consolidation.await_args.kwargs["agenda_updates"] == []

    async def test_entities_are_attached_to_the_returned_entry(
        self, boundaries: Boundaries
    ) -> None:
        fact = make_fact("x")
        boundaries.reconcile.return_value = [make_reconciled(fact)]
        entities = [MagicMock()]

        def entities_for(ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Any]]:
            return {ids[0]: entities}

        boundaries.get_entities_for_memories.side_effect = lambda ids: entities_for(ids)
        with patch.object(ingestion, "row_to_entry", return_value=MagicMock()) as row_to_entry:
            await retain_single(
                USER, "x", category_path="general", source_type=MemorySourceType.MANUAL
            )
        assert row_to_entry.call_args.args[1] == entities

    async def test_missing_entity_lookup_defaults_to_an_empty_list(
        self, boundaries: Boundaries
    ) -> None:
        # A memory with no linked entities must surface as an empty list, not None.
        fact = make_fact("x")
        boundaries.reconcile.return_value = [make_reconciled(fact)]
        boundaries.get_entities_for_memories.return_value = {}
        with patch.object(ingestion, "row_to_entry", return_value=MagicMock()) as row_to_entry:
            await retain_single(
                USER, "x", category_path="general", source_type=MemorySourceType.MANUAL
            )
        assert row_to_entry.call_args.args[1] == []

    async def test_free_user_at_the_cap_gets_a_loud_limit_error(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.get_cached_plan_type.return_value = PlanType.FREE
        boundaries.get_cached_live_count.return_value = None
        boundaries.count_live_memories.return_value = FREE_MEMORY_FACT_LIMIT
        fact = make_fact("x")
        boundaries.reconcile.return_value = [make_reconciled(fact)]
        with patch.object(ingestion, "row_to_entry", return_value=MagicMock()):
            with pytest.raises(MemoryLimitReachedError) as exc:
                await retain_single(
                    USER, "x", category_path="general", source_type=MemorySourceType.MANUAL
                )
        assert exc.value.limit == FREE_MEMORY_FACT_LIMIT
        assert str(exc.value) == (
            f"Free plan memory limit reached ({FREE_MEMORY_FACT_LIMIT} saved memories). "
            "Upgrade to Pro for unlimited memories."
        )
        boundaries.get_cached_plan_type.assert_awaited_once_with(USER)
        assert boundaries.inserted_records == []
        boundaries.adjust_live_count.assert_not_awaited()

    async def test_free_user_with_cached_room_still_stores_the_fact(
        self, boundaries: Boundaries
    ) -> None:
        # 39 cached live facts leaves 11 >= growth(1) + margin: the cached
        # budget decides without consulting the authoritative COUNT.
        boundaries.get_cached_plan_type.return_value = PlanType.FREE
        boundaries.get_cached_live_count.return_value = FREE_MEMORY_FACT_LIMIT - 11
        boundaries.count_live_memories.return_value = 0
        fact = make_fact("x")
        boundaries.reconcile.return_value = [make_reconciled(fact)]
        with patch.object(ingestion, "row_to_entry", return_value=MagicMock()):
            retained = await retain_single(
                USER, "x", category_path="general", source_type=MemorySourceType.MANUAL
            )
        assert retained.outcome is ReconcileOutcome.NEW
        assert [record.content for record in boundaries.inserted_records] == ["x"]
        boundaries.count_live_memories.assert_not_awaited()
        boundaries.set_cached_live_count.assert_not_awaited()

    async def test_free_user_with_exactly_one_slot_still_stores_the_fact(
        self, boundaries: Boundaries
    ) -> None:
        # remaining == 1: the cap check is `<= 0`, so a single free slot is
        # still enough for a growth fact.
        boundaries.get_cached_plan_type.return_value = PlanType.FREE
        boundaries.get_cached_live_count.return_value = None
        boundaries.count_live_memories.return_value = FREE_MEMORY_FACT_LIMIT - 1
        fact = make_fact("x")
        boundaries.reconcile.return_value = [make_reconciled(fact)]
        with patch.object(ingestion, "row_to_entry", return_value=MagicMock()):
            retained = await retain_single(
                USER, "x", category_path="general", source_type=MemorySourceType.MANUAL
            )
        assert retained.outcome is ReconcileOutcome.NEW
        assert [record.content for record in boundaries.inserted_records] == ["x"]

    async def test_extends_is_growth_and_respects_the_cap(self, boundaries: Boundaries) -> None:
        boundaries.get_cached_plan_type.return_value = PlanType.FREE
        boundaries.get_cached_live_count.return_value = FREE_MEMORY_FACT_LIMIT
        boundaries.count_live_memories.return_value = FREE_MEMORY_FACT_LIMIT
        fact = make_fact("x")
        boundaries.reconcile.return_value = [
            make_reconciled(fact, ReconcileOutcome.EXTENDS, target_memory_id="t1")
        ]
        with patch.object(ingestion, "row_to_entry", return_value=MagicMock()):
            with pytest.raises(MemoryLimitReachedError):
                await retain_single(
                    USER, "x", category_path="general", source_type=MemorySourceType.MANUAL
                )

    async def test_updates_are_allowed_at_the_cap(self, boundaries: Boundaries) -> None:
        # Zero-growth outcomes never consult the cap — a revision is allowed
        # even when the live set is full.
        boundaries.get_cached_plan_type.return_value = PlanType.FREE
        boundaries.get_cached_live_count.return_value = FREE_MEMORY_FACT_LIMIT
        boundaries.count_live_memories.return_value = FREE_MEMORY_FACT_LIMIT
        fact = make_fact("x")
        boundaries.reconcile.return_value = [
            make_reconciled(fact, ReconcileOutcome.UPDATES, target_memory_id="old")
        ]
        with patch.object(ingestion, "row_to_entry", return_value=MagicMock()):
            retained = await retain_single(
                USER, "x", category_path="general", source_type=MemorySourceType.MANUAL
            )
        assert retained.outcome is ReconcileOutcome.UPDATES
        boundaries.count_live_memories.assert_not_awaited()
        boundaries.get_cached_live_count.assert_not_awaited()

    async def test_missing_folder_routes_through_the_categorizer(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.get_folder_tree.return_value = [("life", 1)]
        fact = make_fact("remember the gate code")
        boundaries.reconcile.return_value = [make_reconciled(fact)]
        with patch.object(ingestion, "row_to_entry", return_value=MagicMock()):
            await retain_single(USER, "remember the gate code", source_type=MemorySourceType.MANUAL)
        boundaries.get_folder_tree.assert_awaited_once_with(USER)
        assert boundaries.categorize_fact.await_args.args == ("remember the gate code",)
        assert boundaries.categorize_fact.await_args.kwargs["user_id"] == USER
        assert boundaries.categorize_fact.await_args.kwargs["folder_tree"] == "- life (1)"
        # The ingestion timestamp must be UTC-aware — a naive datetime would
        # silently shift the fact's relative-date resolution.
        assert boundaries.categorize_fact.await_args.kwargs["current_date"].tzinfo is UTC


class TestRetain:
    async def test_nothing_extracted_returns_an_empty_result_without_writing(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.extract_memories.return_value = ExtractedMemoryBatch()
        result = await retain(
            USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
        )
        assert result == RetainResult(facts_extracted=0)
        boundaries.embed_batch.assert_not_awaited()
        boundaries.reconcile.assert_not_awaited()
        assert boundaries.inserted_records == []

    async def test_empty_run_emits_an_empty_success_context(self, boundaries: Boundaries) -> None:
        boundaries.extract_memories.return_value = ExtractedMemoryBatch()
        with patch.object(ingestion.log, "set") as log_set:
            await retain(
                USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
            )
        assert log_set.call_count == 2
        assert log_set.call_args_list[0].kwargs == {
            "user": {"id": USER},
            "memory": {"operation": "retain", "source_type": "conversation"},
        }
        assert log_set.call_args_list[1].kwargs == {
            "memory": {
                "operation": "retain",
                "source_type": "conversation",
                "facts_extracted": 0,
                "result_count": 0,
                "success": True,
            }
        }

    async def test_full_run_emits_counts_and_timings_on_the_success_context(
        self, boundaries: Boundaries
    ) -> None:
        parent = make_row()
        boundaries.get_memories_by_ids.return_value = [parent]
        boundaries.supersede_memory.return_value = make_row()
        facts = [make_fact(f"f{index}") for index in range(4)]
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(facts=facts)
        boundaries.reconcile.return_value = [
            make_reconciled(facts[0], embedding=[1.0]),
            make_reconciled(
                facts[1],
                ReconcileOutcome.EXTENDS,
                embedding=[2.0],
                target_memory_id=str(parent.id),
            ),
            make_reconciled(
                facts[2], ReconcileOutcome.UPDATES, embedding=[3.0], target_memory_id="old"
            ),
            make_reconciled(
                facts[3], ReconcileOutcome.DUPLICATE, embedding=[4.0], target_memory_id="old"
            ),
        ]
        with patch.object(ingestion.log, "set") as log_set:
            await retain(
                USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
            )
        assert log_set.call_count == 2
        assert log_set.call_args_list[0].kwargs == {
            "user": {"id": USER},
            "memory": {"operation": "retain", "source_type": "conversation"},
        }
        completion = log_set.call_args_list[1].kwargs["memory"]
        assert completion["operation"] == "retain"
        assert completion["source_type"] == "conversation"
        assert completion["success"] is True
        assert completion["facts_extracted"] == 4
        assert completion["result_count"] == 3
        assert completion["new_count"] == 1
        assert completion["updated_count"] == 1
        assert completion["extended_count"] == 1
        assert completion["duplicate_count"] == 1
        assert completion["entities_linked"] == 0
        assert completion["edges_added"] == 0
        assert completion["episode_entries"] == 0
        assert set(completion["timings"]) == {
            "context_ms",
            "extract_ms",
            "embed_ms",
            "reconcile_ms",
            "apply_ms",
            "episodes_ms",
            "chunks_ms",
            "total_ms",
        }
        assert all(isinstance(value, float) for value in completion["timings"].values())

    async def test_agenda_only_extraction_still_schedules_the_agenda_document(
        self, boundaries: Boundaries
    ) -> None:
        # An open loop closing with no new durable fact and no journal line
        # must not silently drop the agenda update.
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(
            agenda_updates=["GAIA owes the user the Q3 draft"]
        )
        await retain(
            USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
        )
        boundaries.schedule_consolidation.assert_awaited_once()
        assert boundaries.schedule_consolidation.await_args.kwargs["agenda_updates"] == [
            "GAIA owes the user the Q3 draft"
        ]
        boundaries.schedule_vfs_sync.assert_called_once_with(USER)

    async def test_journal_only_extraction_is_persisted(self, boundaries: Boundaries) -> None:
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(
            episode_entries=["Asked GAIA to draft an email"]
        )
        result = await retain(
            USER,
            [{"role": "user", "content": "hi"}],
            source_type=MemorySourceType.CONVERSATION,
            now=datetime(2026, 3, 5, 9, 30, tzinfo=UTC),
        )
        assert result.episode_entries == 1
        assert result.facts_extracted == 0
        user_id, day, entries = boundaries.append_episode_entries.await_args.args
        assert user_id == USER
        assert day == date_type(2026, 3, 5)
        assert entries[0]["text"] == "Asked GAIA to draft an email"

    async def test_counts_from_apply_are_reported_on_the_result(
        self, boundaries: Boundaries
    ) -> None:
        facts = [make_fact("a"), make_fact("b")]
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(facts=facts)
        boundaries.supersede_memory.return_value = make_row()
        boundaries.reconcile.return_value = [
            make_reconciled(facts[0], embedding=[1.0]),
            make_reconciled(
                facts[1], ReconcileOutcome.UPDATES, embedding=[2.0], target_memory_id="old"
            ),
        ]
        result = await retain(
            USER,
            [{"role": "user", "content": "hi"}],
            source_type=MemorySourceType.CONVERSATION,
        )
        assert result.facts_extracted == 2
        assert result.new == 1
        assert result.updated == 1

    async def test_free_cap_trims_the_batch_and_reports_the_drop(
        self, boundaries: Boundaries
    ) -> None:
        # 48 live facts = 2 free slots; the batch grows by 3 (NEW + EXTENDS +
        # NEW), so the last growth fact in reconciliation order is dropped.
        parent = make_row()
        boundaries.get_memories_by_ids.return_value = [parent]
        boundaries.supersede_memory.return_value = make_row()
        boundaries.get_cached_plan_type.return_value = PlanType.FREE
        boundaries.get_cached_live_count.return_value = 48
        boundaries.count_live_memories.return_value = 48
        facts = [make_fact(f"f{index}") for index in range(5)]
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(facts=facts)
        boundaries.reconcile.return_value = [
            make_reconciled(facts[0], embedding=[1.0]),
            make_reconciled(
                facts[1],
                ReconcileOutcome.EXTENDS,
                embedding=[2.0],
                target_memory_id=str(parent.id),
            ),
            make_reconciled(
                facts[2], ReconcileOutcome.UPDATES, embedding=[3.0], target_memory_id="old"
            ),
            make_reconciled(
                facts[3], ReconcileOutcome.DUPLICATE, embedding=[4.0], target_memory_id="old"
            ),
            make_reconciled(facts[4], embedding=[5.0]),
        ]
        with patch.object(ingestion.log, "info") as log_info:
            result = await retain(
                USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
            )
        log_info.assert_called_once_with(
            "memory_cap_reached",
            event_name="memory_cap_reached",
            user_id=USER,
            dropped=1,
            limit=FREE_MEMORY_FACT_LIMIT,
        )
        boundaries.count_live_memories.assert_awaited_once_with(USER)
        boundaries.set_cached_live_count.assert_awaited_once_with(USER, 48)
        assert result.facts_extracted == 5
        assert (result.new, result.extended, result.updated, result.duplicates) == (1, 1, 1, 1)
        # Only the admitted facts reach the DB insert: f4 was trimmed before
        # apply, and the UPDATES row is written via supersede, not insert.
        assert [record.content for record in boundaries.inserted_records] == ["f0", "f1"]
        assert all(record.user_id == USER for record in boundaries.inserted_records)
        superseded = boundaries.supersede_memory.await_args
        assert superseded.args[2].content == "f2"
        assert superseded.args[2].user_id == USER
        boundaries.adjust_live_count.assert_awaited_once_with(USER, 2)

    async def test_free_cap_boundary_still_consults_the_authoritative_count(
        self, boundaries: Boundaries
    ) -> None:
        # growth = 3 (NEW + EXTENDS + NEW) with only 12 cached slots left: the
        # cache is trusted only when the batch clears the safety margin, so
        # the COUNT must decide — and the growth tally must count EXTENDS or
        # the cache would have been trusted.
        parent = make_row()
        boundaries.get_memories_by_ids.return_value = [parent]
        boundaries.get_cached_plan_type.return_value = PlanType.FREE
        boundaries.get_cached_live_count.return_value = 38
        boundaries.count_live_memories.return_value = 38
        facts = [make_fact("a"), make_fact("b"), make_fact("c")]
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(facts=facts)
        boundaries.reconcile.return_value = [
            make_reconciled(facts[0], embedding=[1.0]),
            make_reconciled(
                facts[1],
                ReconcileOutcome.EXTENDS,
                embedding=[2.0],
                target_memory_id=str(parent.id),
            ),
            make_reconciled(facts[2], embedding=[3.0]),
        ]
        with patch.object(ingestion.log, "info") as log_info:
            result = await retain(
                USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
            )
        log_info.assert_not_called()
        assert result.facts_extracted == 3
        assert (result.new, result.extended) == (2, 1)
        assert [record.content for record in boundaries.inserted_records] == ["a", "b", "c"]
        boundaries.count_live_memories.assert_awaited_once_with(USER)
        boundaries.set_cached_live_count.assert_awaited_once_with(USER, 38)

    async def test_free_cap_with_plenty_of_cached_room_skips_the_count(
        self, boundaries: Boundaries
    ) -> None:
        # growth = 2 with exactly 12 cached slots left: 12 >= growth(2) +
        # margin(10), so the cache decides without the authoritative COUNT.
        facts = [make_fact("a"), make_fact("b")]
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(facts=facts)
        boundaries.reconcile.return_value = [
            make_reconciled(facts[0], embedding=[1.0]),
            make_reconciled(facts[1], embedding=[2.0]),
        ]
        boundaries.get_cached_plan_type.return_value = PlanType.FREE
        boundaries.get_cached_live_count.return_value = 38
        result = await retain(
            USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
        )
        assert result.new == 2
        boundaries.count_live_memories.assert_not_awaited()
        boundaries.set_cached_live_count.assert_not_awaited()

    async def test_extraction_receives_the_prior_context(self, boundaries: Boundaries) -> None:
        boundaries.get_folder_tree.return_value = [("work", 4)]
        boundaries.get_recent_facts.return_value = ["sam likes tea"]
        boundaries.get_episode.return_value = make_episode(
            entries=[{"time": "09:00", "text": "already journaled"}]
        )
        boundaries.extract_memories.return_value = ExtractedMemoryBatch()
        await retain(
            USER,
            [{"role": "user", "content": "hi"}],
            source_type=MemorySourceType.CONVERSATION,
            extraction_hints="focus on preferences",
            user_name="Sam",
        )
        kwargs = boundaries.extract_memories.await_args.kwargs
        assert kwargs["user_id"] == USER
        assert kwargs["user_name"] == "Sam"
        assert kwargs["folder_tree"] == "- work (4)"
        assert kwargs["recent_facts"] == ["sam likes tea"]
        assert kwargs["journaled_today"] == ["already journaled"]
        assert kwargs["extraction_hints"] == "focus on preferences"
        boundaries.get_folder_tree.assert_awaited_once_with(USER)
        boundaries.get_recent_facts.assert_awaited_once_with(USER, limit=RECENT_FACTS_LIMIT)
        user_id, day = boundaries.get_episode.await_args.args
        assert user_id == USER
        assert isinstance(day, date_type)

    async def test_anonymous_caller_gets_the_default_user_name(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.extract_memories.return_value = ExtractedMemoryBatch()
        messages = [{"role": "user", "content": "hi"}]
        await retain(USER, messages, source_type=MemorySourceType.CONVERSATION)
        assert boundaries.extract_memories.await_args.kwargs["user_name"] == "the user"
        assert boundaries.extract_memories.await_args.args[0] == messages
        assert boundaries.extract_memories.await_args.kwargs["user_id"] == USER

    async def test_journaled_today_is_empty_when_no_episode_exists(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.get_episode.return_value = None
        boundaries.extract_memories.return_value = ExtractedMemoryBatch()
        await retain(
            USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
        )
        assert boundaries.extract_memories.await_args.kwargs["journaled_today"] == []

    async def test_journaled_today_entries_missing_text_become_empty_strings(
        self, boundaries: Boundaries
    ) -> None:
        # A journal line without a "text" key must not leak None or a
        # placeholder into the extraction prompt.
        boundaries.get_episode.return_value = make_episode(
            entries=[{"time": "09:00"}, {"time": "10:00", "text": "real"}]
        )
        boundaries.extract_memories.return_value = ExtractedMemoryBatch()
        await retain(
            USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
        )
        assert boundaries.extract_memories.await_args.kwargs["journaled_today"] == [
            "",
            "real",
        ]

    async def test_explicit_now_drives_every_timestamp(self, boundaries: Boundaries) -> None:
        replay = datetime(2019, 7, 4, 8, 15, tzinfo=UTC)
        fact = make_fact("a")
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(
            facts=[fact], episode_entries=["did a thing"]
        )
        boundaries.reconcile.return_value = [make_reconciled(fact, embedding=[1.0])]
        await retain(
            USER,
            [{"role": "user", "content": "hi"}],
            source_type=MemorySourceType.MIGRATION,
            source_id="sess-1",
            now=replay,
        )
        assert boundaries.extract_memories.await_args.kwargs["current_date"] == replay
        assert boundaries.get_episode.await_args.args[1] == replay.date()
        assert boundaries.inserted_records[0].mentioned_at == replay
        assert boundaries.inserted_records[0].source_id == "sess-1"
        _, day, entries = boundaries.append_episode_entries.await_args.args
        assert day == date_type(2019, 7, 4)
        assert entries[0]["time"] == "08:15"
        chunk = boundaries.upsert_conversation_chunks.await_args.args[0][0]
        assert chunk["metadata"]["date"] == "2019-07-04"

    async def test_email_ingestion_drops_journal_lines_and_agenda_updates(
        self, boundaries: Boundaries
    ) -> None:
        # An inbox is not the user's diary or to-do list.
        fact = make_fact("the user runs a startup")
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(
            facts=[fact],
            episode_entries=["respond to customer X"],
            agenda_updates=["resolve ticket Y"],
        )
        boundaries.reconcile.return_value = [make_reconciled(fact, embedding=[1.0])]
        result = await retain(
            USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.EMAIL
        )
        assert result.episode_entries == 0
        boundaries.append_episode_entries.assert_not_awaited()
        assert boundaries.schedule_consolidation.await_args.kwargs["agenda_updates"] == []

    async def test_email_with_no_facts_writes_nothing(self, boundaries: Boundaries) -> None:
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(
            episode_entries=["respond to customer X"], agenda_updates=["resolve ticket Y"]
        )
        result = await retain(
            USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.EMAIL
        )
        assert result == RetainResult(facts_extracted=0)
        boundaries.append_episode_entries.assert_not_awaited()
        boundaries.schedule_consolidation.assert_not_awaited()

    async def test_rolled_over_days_are_summarized_during_ingestion(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(episode_entries=["a line"])
        boundaries.get_unsummarized_episode_dates.return_value = [date_type(2026, 3, 4)]
        boundaries.get_episode.side_effect = [
            None,
            make_episode(entries=[{"time": "10:00", "text": "yesterday"}]),
        ]
        await retain(
            USER,
            [{"role": "user", "content": "hi"}],
            source_type=MemorySourceType.CONVERSATION,
            now=datetime(2026, 3, 5, tzinfo=UTC),
        )
        boundaries.get_unsummarized_episode_dates.assert_awaited_once_with(
            USER, date_type(2026, 3, 5)
        )
        assert boundaries.set_episode_summary.await_args.args[1] == date_type(2026, 3, 4)

    async def test_transcript_is_chunked_under_the_session_id(self, boundaries: Boundaries) -> None:
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(episode_entries=["a line"])
        await retain(
            USER,
            [{"role": "user", "content": "the transcript body"}],
            source_type=MemorySourceType.CONVERSATION,
            source_id="conv-42",
        )
        chunk = boundaries.upsert_conversation_chunks.await_args.args[0][0]
        assert chunk["id"].startswith(f"{USER}:conv-42:")
        assert chunk["document"] == "user: the transcript body"

    async def test_caches_are_invalidated_after_a_write(self, boundaries: Boundaries) -> None:
        fact = make_fact("a")
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(facts=[fact])
        boundaries.reconcile.return_value = [make_reconciled(fact, embedding=[1.0])]
        await retain(
            USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
        )
        boundaries.invalidate_caches.assert_awaited_once_with(USER)
        # Without an explicit `now`, the ingestion timestamp must still be
        # UTC-aware (a naive datetime would skew relative-date resolution).
        assert boundaries.extract_memories.await_args.kwargs["current_date"].tzinfo is UTC
        assert boundaries.inserted_records[0].mentioned_at.tzinfo is UTC

    async def test_only_stored_facts_drive_consolidation(self, boundaries: Boundaries) -> None:
        stored = make_fact("kept", kind=MemoryKind.EXPERIENCE)
        dropped = make_fact("dupe", kind=MemoryKind.EXPERIENCE)
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(facts=[stored, dropped])
        boundaries.reconcile.return_value = [
            make_reconciled(stored, embedding=[1.0]),
            make_reconciled(
                dropped, ReconcileOutcome.DUPLICATE, embedding=[2.0], target_memory_id="t"
            ),
        ]
        with patch.object(ingestion, "infer_doc_types", return_value=set()) as infer:
            await retain(
                USER,
                [{"role": "user", "content": "hi"}],
                source_type=MemorySourceType.CONVERSATION,
            )
        assert [fact.content for fact in infer.call_args.args[0]] == ["kept"]

    async def test_facts_are_embedded_in_extraction_order(self, boundaries: Boundaries) -> None:
        facts = [make_fact("first"), make_fact("second")]
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(facts=facts)
        boundaries.reconcile.return_value = [
            make_reconciled(facts[0], embedding=[1.0]),
            make_reconciled(facts[1], embedding=[2.0]),
        ]
        await retain(
            USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
        )
        assert boundaries.embed_batch.await_args_list[0].args[0] == ["first", "second"]
        user_id, reconcile_facts, embeddings = boundaries.reconcile.await_args.args
        assert user_id == USER
        assert reconcile_facts == facts
        assert embeddings == [[0.0, 0.5], [1.0, 0.5]]
