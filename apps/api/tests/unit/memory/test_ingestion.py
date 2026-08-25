"""Unit tests for app.memory.ingestion — the memory write path.

Every external boundary (Postgres, Chroma, the embedding/extraction models,
the projection and consolidation schedulers) is mocked; the reconciliation
application, chunking, journaling and scheduling logic under test is real.

``insert_memories`` is faked to populate ``record.id`` the way a real flush
does, because the Chroma vector ids are derived from it after the insert.
"""

from dataclasses import dataclass, field
from datetime import UTC, date as date_type, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from app.constants.memory import (
    AGENDA_CATEGORY_PATH,
    AGENDA_ITEM_TTL_DAYS,
    CATEGORY_PATH_MAX_DEPTH,
    DEFAULT_MEMORY_IMPORTANCE,
    FREE_MEMORY_CAP_COUNT_SAFETY_MARGIN,
    FREE_MEMORY_FACT_LIMIT,
    RECONCILE_SIMILARITY_THRESHOLD,
    STATE_FACT_TTL_DAYS,
    TRANSCRIPT_CHUNK_MAX_CHARS,
    TRANSCRIPT_CHUNK_OVERLAP_CHARS,
    TRANSCRIPT_CHUNK_TURNS,
    TRANSCRIPT_CHUNKS_PER_SESSION_CAP,
    MemoryDocType,
    MemoryKind,
    MemoryRelationType,
    MemoryShelfLife,
    MemorySourceType,
    ReconcileOutcome,
)
from app.memory import ingestion
from app.memory.ingestion import RetainResult, retain, retain_single, summarize_episode
from app.memory.reconciliation import ReconciledFact
from app.memory.schemas import (
    AgendaUpdate,
    ExtractedEdge,
    ExtractedEntity,
    ExtractedFact,
    ExtractedMemoryBatch,
    FactCategorization,
)
from app.models.memory_db_models import MemoryRecord
from app.models.payment_models import PlanType
from tests.helpers import captured_wide_event

USER = "user-1"
NOW = datetime(2026, 8, 24, tzinfo=UTC)


def make_fact(
    content: str = "sam likes green tea",
    *,
    kind: MemoryKind = MemoryKind.FACT,
    shelf_life: MemoryShelfLife = MemoryShelfLife.DURABLE,
    category_path: str = "preferences",
    importance: float = 0.5,
    entities: list[ExtractedEntity] | None = None,
    edges: list[ExtractedEdge] | None = None,
    occurred_start: datetime | None = None,
    occurred_end: datetime | None = None,
) -> ExtractedFact:
    return ExtractedFact(
        content=content,
        kind=kind,
        shelf_life=shelf_life,
        category_path=category_path,
        importance=importance,
        entities=entities or [],
        edges=edges or [],
        occurred_start=occurred_start,
        occurred_end=occurred_end,
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
    render_agenda_document: AsyncMock
    query_similar: AsyncMock
    forget_memory: AsyncMock
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
    }
    chroma_patches = {
        "upsert_memories": AsyncMock(return_value=None),
        "set_memory_flags": AsyncMock(return_value=None),
        "upsert_conversation_chunks": AsyncMock(return_value=None),
        "upsert_episode": AsyncMock(return_value=None),
        "query_similar": AsyncMock(return_value=[]),
    }
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
        "render_agenda_document": AsyncMock(return_value=None),
        "forget_memory": AsyncMock(return_value=True),
    }
    vfs_mock = MagicMock(return_value=None)

    with (
        patch.multiple(ingestion.pg_store, insert_memories=insert_mock, **patches),
        patch.multiple(ingestion.chroma_store, **chroma_patches),
        patch.multiple(ingestion, schedule_memory_vfs_sync=vfs_mock, **module_patches),
        # Paid plan -> the free memory cap never applies, so these tests exercise
        # ingestion itself without the cap's plan/count lookups reaching real infra.
        patch.object(
            ingestion.payment_service,
            "get_cached_plan_type",
            AsyncMock(return_value=PlanType.PRO),
        ),
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
            render_agenda_document=module_patches["render_agenda_document"],
            query_similar=chroma_patches["query_similar"],
            forget_memory=module_patches["forget_memory"],
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


class TestBuildRecord:
    def test_maps_every_fact_field_onto_the_row(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 2, tzinfo=UTC)
        fact = make_fact(
            "sam moved to berlin",
            kind=MemoryKind.EXPERIENCE,
            category_path="life/moves",
            importance=0.9,
            occurred_start=start,
            occurred_end=end,
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
        assert record.source_type == MemorySourceType.EMAIL.value
        assert record.source_id == "msg-9"

    def test_a_durable_fact_never_expires(self) -> None:
        record = ingestion._build_record(
            make_fact(shelf_life=MemoryShelfLife.DURABLE),
            user_id=USER,
            source_type=MemorySourceType.CONVERSATION,
            source_id=None,
        )
        assert record.forget_after is None

    def test_a_state_fact_expires_after_the_state_window(self) -> None:
        now = datetime(2026, 3, 1, tzinfo=UTC)
        record = ingestion._build_record(
            make_fact("gmail is disconnected", shelf_life=MemoryShelfLife.STATE),
            user_id=USER,
            source_type=MemorySourceType.CONVERSATION,
            source_id=None,
            mentioned_at=now,
        )
        assert record.forget_after == now + timedelta(days=STATE_FACT_TTL_DAYS)

    def test_an_agenda_item_expires_after_the_agenda_window(self) -> None:
        now = datetime(2026, 3, 1, tzinfo=UTC)
        record = ingestion._build_record(
            make_fact("file the tax return", shelf_life=MemoryShelfLife.TASK),
            user_id=USER,
            source_type=MemorySourceType.CONVERSATION,
            source_id=None,
            mentioned_at=now,
        )
        assert record.forget_after == now + timedelta(days=AGENDA_ITEM_TTL_DAYS)

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

    async def test_extends_supersedes_its_parent_and_retires_its_vector(
        self, boundaries: Boundaries
    ) -> None:
        parent = make_row(content="sam drinks tea")
        superseding = make_row(content="sam drinks matcha")
        boundaries.supersede_memory.return_value = superseding
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
        assert (applied.new, applied.extended) == (0, 1)
        # Two rows about the same subject-attribute must never both be live.
        target_id, _user, _record, relation = boundaries.supersede_memory.await_args.args
        assert target_id == str(parent.id)
        assert relation is MemoryRelationType.EXTENDS
        boundaries.set_memory_flags.assert_awaited_once_with(str(parent.id), is_latest=False)

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
        boundaries.supersede_memory.assert_not_awaited()

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

    async def test_updates_without_a_target_id_is_stored_rather_than_dropped(
        self, boundaries: Boundaries
    ) -> None:
        # A supersession verdict with nothing to supersede used to vanish
        # entirely; the fact itself is still real, so it lands as a plain row.
        reconciled = [
            make_reconciled(make_fact("x"), ReconcileOutcome.UPDATES, target_memory_id=None)
        ]
        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert (applied.new, applied.updated) == (1, 0)
        boundaries.supersede_memory.assert_not_awaited()
        assert [record.content for record in boundaries.inserted_records] == ["x"]

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
            source_id=None,
            mentioned_at=replay,
        )
        assert [record.mentioned_at for record, _ in applied.inserted] == [replay, replay]

    async def test_empty_reconciliation_writes_nothing(self, boundaries: Boundaries) -> None:
        applied = await ingestion._apply_reconciled(
            USER, [], source_type=MemorySourceType.CONVERSATION, source_id=None
        )
        assert applied == ingestion._ApplyResult(
            inserted=[], duplicates=0, new=0, updated=0, extended=0
        )
        assert boundaries.vector_items == []

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


class TestSchedulePostIngest:
    async def test_projection_sync_always_runs(self, boundaries: Boundaries) -> None:
        await ingestion._schedule_post_ingest(USER, inserted_facts=[])
        boundaries.schedule_vfs_sync.assert_called_once_with(USER)

    async def test_no_touched_documents_skips_consolidation(self, boundaries: Boundaries) -> None:
        await ingestion._schedule_post_ingest(USER, inserted_facts=[])
        boundaries.schedule_consolidation.assert_not_awaited()

    async def test_a_durable_fact_schedules_its_document(self, boundaries: Boundaries) -> None:
        await ingestion._schedule_post_ingest(
            USER,
            inserted_facts=[make_fact("sam is vegetarian", category_path="food-preferences")],
        )
        user_id, doc_types = boundaries.schedule_consolidation.await_args.args
        assert user_id == USER
        assert MemoryDocType.MEMORY_MD in doc_types

    async def test_an_agenda_row_never_feeds_a_consolidated_document(
        self, boundaries: Boundaries
    ) -> None:
        # agenda.md is rendered from its rows, and a task must not leak into
        # the always-injected identity document either.
        await ingestion._schedule_post_ingest(
            USER,
            inserted_facts=[
                make_fact(
                    "owes the user a draft",
                    shelf_life=MemoryShelfLife.TASK,
                    category_path=AGENDA_CATEGORY_PATH,
                )
            ],
        )
        boundaries.schedule_consolidation.assert_not_awaited()

    async def test_a_state_fact_never_feeds_a_consolidated_document(
        self, boundaries: Boundaries
    ) -> None:
        await ingestion._schedule_post_ingest(
            USER,
            inserted_facts=[
                make_fact(
                    "sam has 18 active workflows",
                    shelf_life=MemoryShelfLife.STATE,
                    category_path="work",
                )
            ],
        )
        boundaries.schedule_consolidation.assert_not_awaited()


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
        assert boundaries.categorize_fact.await_args.kwargs["folder_tree"] == "- work (2)"

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
        assert row_to_entry.call_args.args[0] is boundaries.inserted_records[0]

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
        with pytest.raises(ValueError, match="no longer exists"):
            await retain_single(USER, "x", source_type=MemorySourceType.MANUAL)

    async def test_duplicate_without_a_target_id_raises(self, boundaries: Boundaries) -> None:
        boundaries.reconcile.return_value = [
            make_reconciled(make_fact("x"), ReconcileOutcome.DUPLICATE, target_memory_id=None)
        ]
        with pytest.raises(ValueError, match="no longer exists"):
            await retain_single(USER, "x", source_type=MemorySourceType.MANUAL)
        boundaries.get_memory.assert_not_awaited()

    async def test_reconciler_returning_no_verdict_raises_a_clear_error(
        self, boundaries: Boundaries
    ) -> None:
        # The reconcile LLM can return fewer decisions than facts, which drops
        # the fact entirely. The user-facing add-memory path must not surface
        # that as a bare IndexError.
        boundaries.reconcile.return_value = []
        with pytest.raises(ValueError, match="reconcil"):
            await retain_single(USER, "x", source_type=MemorySourceType.MANUAL)

    async def test_follow_ups_are_scheduled_for_the_stored_fact(
        self, boundaries: Boundaries
    ) -> None:
        fact = make_fact("went to berlin", kind=MemoryKind.EXPERIENCE, category_path="life")
        boundaries.reconcile.return_value = [make_reconciled(fact)]
        with patch.object(ingestion, "row_to_entry", return_value=MagicMock()):
            await retain_single(
                USER, "went to berlin", category_path="life", source_type=MemorySourceType.MANUAL
            )
        boundaries.invalidate_caches.assert_awaited_once_with(USER)
        boundaries.schedule_vfs_sync.assert_called_once_with(USER)
        assert MemoryDocType.USER_MD in boundaries.schedule_consolidation.await_args.args[1]

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

    async def test_agenda_only_extraction_rewrites_the_agenda_document(
        self, boundaries: Boundaries
    ) -> None:
        # An open loop with no new durable fact and no journal line must still
        # land as a real row and reach the rendered agenda.
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(
            agenda_updates=[AgendaUpdate(item="GAIA owes the user the Q3 draft", resolved=False)]
        )
        boundaries.reconcile.side_effect = lambda _user, facts, embeddings: [
            make_reconciled(fact, embedding=embedding) for fact, embedding in zip(facts, embeddings)
        ]
        await retain(
            USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
        )
        assert [record.content for record in boundaries.inserted_records] == [
            "GAIA owes the user the Q3 draft"
        ]
        boundaries.render_agenda_document.assert_awaited_once_with(USER)
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
        _, day, entries = boundaries.append_episode_entries.await_args.args
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
        assert kwargs["user_name"] == "Sam"
        assert kwargs["folder_tree"] == "- work (4)"
        assert kwargs["recent_facts"] == ["sam likes tea"]
        assert kwargs["journaled_today"] == ["already journaled"]
        assert kwargs["extraction_hints"] == "focus on preferences"

    async def test_anonymous_caller_gets_the_default_user_name(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.extract_memories.return_value = ExtractedMemoryBatch()
        await retain(
            USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
        )
        assert boundaries.extract_memories.await_args.kwargs["user_name"] == "the user"

    async def test_journaled_today_is_empty_when_no_episode_exists(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.get_episode.return_value = None
        boundaries.extract_memories.return_value = ExtractedMemoryBatch()
        await retain(
            USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
        )
        assert boundaries.extract_memories.await_args.kwargs["journaled_today"] == []

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
            agenda_updates=[AgendaUpdate(item="resolve ticket Y", resolved=False)],
        )
        boundaries.reconcile.return_value = [make_reconciled(fact, embedding=[1.0])]
        result = await retain(
            USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.EMAIL
        )
        assert result.episode_entries == 0
        boundaries.append_episode_entries.assert_not_awaited()
        assert [record.content for record in boundaries.inserted_records] == [
            "the user runs a startup"
        ]
        boundaries.render_agenda_document.assert_not_awaited()

    async def test_email_with_no_facts_writes_nothing(self, boundaries: Boundaries) -> None:
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(
            episode_entries=["respond to customer X"],
            agenda_updates=[AgendaUpdate(item="resolve ticket Y", resolved=False)],
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


@pytest.mark.unit
class TestShelfLifeRouting:
    """A fact's shelf_life decides which store it lands in, not just its expiry."""

    async def test_a_journal_shelf_life_fact_never_reaches_the_fact_store(
        self, boundaries: Boundaries
    ) -> None:
        gaia_output = make_fact(
            "GAIA recommended Roscioli, Armando al Pantheon and Da Enzo",
            shelf_life=MemoryShelfLife.JOURNAL,
        )
        user_fact = make_fact("sam's anniversary is October 19", shelf_life=MemoryShelfLife.DURABLE)
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(
            facts=[gaia_output, user_fact]
        )
        boundaries.reconcile.side_effect = lambda _user, facts, embeddings: [
            make_reconciled(fact, embedding=embedding) for fact, embedding in zip(facts, embeddings)
        ]

        await retain(
            USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
        )

        assert [record.content for record in boundaries.inserted_records] == [
            "sam's anniversary is October 19"
        ]
        journaled = boundaries.append_episode_entries.await_args.args[2]
        assert [entry["text"] for entry in journaled] == [
            "GAIA recommended Roscioli, Armando al Pantheon and Da Enzo"
        ]

    async def test_a_task_shelf_life_fact_becomes_an_agenda_row(
        self, boundaries: Boundaries
    ) -> None:
        commitment = make_fact(
            "sam owes the landlord a signed lease by March 3",
            shelf_life=MemoryShelfLife.TASK,
            category_path="work",
        )
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(facts=[commitment])
        boundaries.reconcile.side_effect = lambda _user, facts, embeddings: [
            make_reconciled(fact, embedding=embedding) for fact, embedding in zip(facts, embeddings)
        ]

        await retain(
            USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
        )

        assert len(boundaries.inserted_records) == 1
        row = boundaries.inserted_records[0]
        assert row.content == "sam owes the landlord a signed lease by March 3"
        assert row.category_path == AGENDA_CATEGORY_PATH
        assert row.forget_after is not None

    async def test_agenda_updates_are_persisted_as_memory_rows(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(
            agenda_updates=[AgendaUpdate(item="ship the billing migration", resolved=False)]
        )
        boundaries.reconcile.side_effect = lambda _user, facts, embeddings: [
            make_reconciled(fact, embedding=embedding) for fact, embedding in zip(facts, embeddings)
        ]

        await retain(
            USER,
            [{"role": "user", "content": "hi"}],
            source_type=MemorySourceType.CONVERSATION,
            source_id="conv-7",
        )

        assert [record.content for record in boundaries.inserted_records] == [
            "ship the billing migration"
        ]
        row = boundaries.inserted_records[0]
        assert row.category_path == AGENDA_CATEGORY_PATH
        assert row.source_id == "conv-7"
        assert row.forget_after is not None

    async def test_a_resolved_agenda_update_forgets_its_open_row(
        self, boundaries: Boundaries
    ) -> None:
        open_row = make_row(content="ship the billing migration", category_path="agenda")
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(
            agenda_updates=[AgendaUpdate(item="ship the billing migration", resolved=True)]
        )
        boundaries.get_memories_by_ids.return_value = [open_row]

        with (
            patch.object(
                ingestion.chroma_store,
                "query_similar",
                AsyncMock(return_value=[(str(open_row.id), 0.99)]),
            ),
            patch.object(ingestion, "forget_memory", AsyncMock(return_value=True)) as forget,
        ):
            await retain(
                USER,
                [{"role": "user", "content": "hi"}],
                source_type=MemorySourceType.CONVERSATION,
            )

        assert forget.await_args.args[:2] == (USER, str(open_row.id))
        assert not boundaries.inserted_records


@pytest.mark.unit
class TestApplyReconciledCounts:
    """Each outcome is counted once — the counts drive the free-plan counter."""

    async def test_every_duplicate_is_counted(self, boundaries: Boundaries) -> None:
        reconciled = [
            make_reconciled(make_fact("dupe a"), ReconcileOutcome.DUPLICATE, target_memory_id="t1"),
            make_reconciled(make_fact("dupe b"), ReconcileOutcome.DUPLICATE, target_memory_id="t2"),
        ]

        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )

        assert applied.duplicates == 2

    async def test_a_duplicate_does_not_stop_the_facts_behind_it(
        self, boundaries: Boundaries
    ) -> None:
        reconciled = [
            make_reconciled(make_fact("dupe"), ReconcileOutcome.DUPLICATE, target_memory_id="t1"),
            make_reconciled(make_fact("kept"), embedding=[1.0]),
        ]

        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )

        assert (applied.new, applied.duplicates) == (1, 1)
        assert [record.content for record in boundaries.inserted_records] == ["kept"]

    async def test_every_extends_is_counted(self, boundaries: Boundaries) -> None:
        boundaries.supersede_memory.return_value = make_row()
        reconciled = [
            make_reconciled(
                make_fact("a"), ReconcileOutcome.EXTENDS, embedding=[1.0], target_memory_id="t1"
            ),
            make_reconciled(
                make_fact("b"), ReconcileOutcome.EXTENDS, embedding=[2.0], target_memory_id="t2"
            ),
        ]

        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )

        assert (applied.extended, applied.updated, applied.new) == (2, 0, 0)

    async def test_every_update_is_counted(self, boundaries: Boundaries) -> None:
        boundaries.supersede_memory.return_value = make_row()
        reconciled = [
            make_reconciled(
                make_fact("a"), ReconcileOutcome.UPDATES, embedding=[1.0], target_memory_id="t1"
            ),
            make_reconciled(
                make_fact("b"), ReconcileOutcome.UPDATES, embedding=[2.0], target_memory_id="t2"
            ),
        ]

        applied = await ingestion._apply_reconciled(
            USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
        )

        assert (applied.updated, applied.extended, applied.new) == (2, 0, 0)

    async def test_the_live_counter_grows_only_by_the_rows_that_are_new(
        self, boundaries: Boundaries
    ) -> None:
        # UPDATES and EXTENDS supersede (net zero) and DUPLICATEs add nothing:
        # counting them would push a free user over the cap on corrections.
        boundaries.supersede_memory.return_value = make_row()
        reconciled = [
            make_reconciled(make_fact("new one"), embedding=[1.0]),
            make_reconciled(
                make_fact("updates one"),
                ReconcileOutcome.UPDATES,
                embedding=[2.0],
                target_memory_id="t1",
            ),
            make_reconciled(
                make_fact("dupe one"),
                ReconcileOutcome.DUPLICATE,
                embedding=[3.0],
                target_memory_id="t2",
            ),
        ]

        with patch.object(ingestion.cap_counter, "adjust_live_count", AsyncMock()) as adjust:
            await ingestion._apply_reconciled(
                USER, reconciled, source_type=MemorySourceType.CONVERSATION, source_id=None
            )

        assert adjust.await_args.args == (USER, 1)


@pytest.mark.unit
class TestForgetAfter:
    def test_a_durable_fact_never_expires(self) -> None:
        assert ingestion._forget_after(MemoryShelfLife.DURABLE, NOW) is None

    def test_a_state_fact_expires_after_the_state_window(self) -> None:
        assert ingestion._forget_after(MemoryShelfLife.STATE, NOW) == NOW + timedelta(
            days=STATE_FACT_TTL_DAYS
        )

    def test_an_agenda_item_expires_after_the_agenda_window(self) -> None:
        assert ingestion._forget_after(MemoryShelfLife.TASK, NOW) == NOW + timedelta(
            days=AGENDA_ITEM_TTL_DAYS
        )

    def test_an_expiry_taken_from_the_clock_is_utc_aware(self) -> None:
        # A naive expiry compares as garbage against the timezone-aware
        # forget_after column and the read-time expiry clause.
        expiry = ingestion._forget_after(MemoryShelfLife.STATE, None)

        assert expiry is not None
        assert expiry.tzinfo is UTC


@pytest.mark.unit
class TestCloseResolvedAgendaItems:
    """Semantic closure of agenda rows a conversation resolved.

    The extractor restates a commitment in its own words when it closes it, so
    the match is by embedding, not by text.
    """

    @staticmethod
    def _agenda_row(content: str = "ship the billing migration") -> MemoryRecord:
        return make_row(content=content, category_path=AGENDA_CATEGORY_PATH)

    async def test_nothing_resolved_does_not_reach_the_index(self, boundaries: Boundaries) -> None:
        assert await ingestion._close_resolved_agenda_items(USER, []) == 0
        boundaries.embed_batch.assert_not_awaited()

    async def test_an_item_with_no_match_closes_nothing(self, boundaries: Boundaries) -> None:
        boundaries.query_similar.return_value = []

        assert await ingestion._close_resolved_agenda_items(USER, ["shipped it"]) == 0
        boundaries.forget_memory.assert_not_awaited()

    async def test_the_search_asks_for_the_single_best_live_match_of_this_user(
        self, boundaries: Boundaries
    ) -> None:
        await ingestion._close_resolved_agenda_items(USER, ["shipped it"])

        call = boundaries.query_similar.await_args
        assert call.args == (USER, [0.0, 0.5])
        assert call.kwargs == {"n": 1, "only_latest": True}

    async def test_a_match_below_the_threshold_is_not_closed(self, boundaries: Boundaries) -> None:
        row = self._agenda_row()
        boundaries.query_similar.return_value = [
            (str(row.id), RECONCILE_SIMILARITY_THRESHOLD - 0.01)
        ]
        boundaries.get_memories_by_ids.return_value = [row]

        assert await ingestion._close_resolved_agenda_items(USER, ["shipped it"]) == 0
        boundaries.forget_memory.assert_not_awaited()

    async def test_a_match_exactly_at_the_threshold_is_closed(self, boundaries: Boundaries) -> None:
        row = self._agenda_row()
        boundaries.query_similar.return_value = [(str(row.id), RECONCILE_SIMILARITY_THRESHOLD)]
        boundaries.get_memories_by_ids.return_value = [row]

        assert await ingestion._close_resolved_agenda_items(USER, ["shipped it"]) == 1

    async def test_a_weak_match_does_not_stop_the_items_behind_it(
        self, boundaries: Boundaries
    ) -> None:
        row = self._agenda_row()
        boundaries.query_similar.side_effect = [
            [("no-match", 0.1)],
            [(str(row.id), 0.95)],
        ]
        boundaries.get_memories_by_ids.return_value = [row]

        assert await ingestion._close_resolved_agenda_items(USER, ["vague", "shipped it"]) == 1

    async def test_the_matched_row_is_fetched_for_this_user_by_id(
        self, boundaries: Boundaries
    ) -> None:
        row = self._agenda_row()
        boundaries.query_similar.return_value = [(str(row.id), 0.95)]
        boundaries.get_memories_by_ids.return_value = [row]

        await ingestion._close_resolved_agenda_items(USER, ["shipped it"])

        assert boundaries.get_memories_by_ids.await_args.args == (USER, [str(row.id)])

    async def test_a_match_whose_row_is_gone_closes_nothing(self, boundaries: Boundaries) -> None:
        boundaries.query_similar.return_value = [("vanished", 0.95)]
        boundaries.get_memories_by_ids.return_value = []

        assert await ingestion._close_resolved_agenda_items(USER, ["shipped it"]) == 0
        boundaries.forget_memory.assert_not_awaited()

    async def test_a_match_outside_the_agenda_folder_does_not_stop_the_scan(
        self, boundaries: Boundaries
    ) -> None:
        # A closure phrase can land on an ordinary fact; that fact must survive,
        # and the next item must still be considered.
        ordinary = make_row(content="sam likes green tea", category_path="preferences")
        agenda = self._agenda_row()
        boundaries.query_similar.side_effect = [
            [(str(ordinary.id), 0.95)],
            [(str(agenda.id), 0.95)],
        ]
        boundaries.get_memories_by_ids.side_effect = [[ordinary], [agenda]]

        closed = await ingestion._close_resolved_agenda_items(USER, ["tea", "shipped it"])

        assert closed == 1
        assert [call.args[1] for call in boundaries.forget_memory.await_args_list] == [
            str(agenda.id)
        ]

    async def test_the_closure_reason_quotes_the_item_that_closed_it(
        self, boundaries: Boundaries
    ) -> None:
        row = self._agenda_row()
        boundaries.query_similar.return_value = [(str(row.id), 0.95)]
        boundaries.get_memories_by_ids.return_value = [row]

        await ingestion._close_resolved_agenda_items(USER, ["shipped the billing migration"])

        assert boundaries.forget_memory.await_args.args == (
            USER,
            str(row.id),
            "agenda item resolved: shipped the billing migration",
        )

    async def test_every_closed_item_is_counted(self, boundaries: Boundaries) -> None:
        first = self._agenda_row("ship the billing migration")
        second = self._agenda_row("file the tax return")
        boundaries.query_similar.side_effect = [
            [(str(first.id), 0.95)],
            [(str(second.id), 0.95)],
        ]
        boundaries.get_memories_by_ids.side_effect = [[first], [second]]

        assert await ingestion._close_resolved_agenda_items(USER, ["one", "two"]) == 2

    async def test_a_row_the_store_refused_to_forget_is_not_counted(
        self, boundaries: Boundaries
    ) -> None:
        row = self._agenda_row()
        boundaries.query_similar.return_value = [(str(row.id), 0.95)]
        boundaries.get_memories_by_ids.return_value = [row]
        boundaries.forget_memory.return_value = False

        assert await ingestion._close_resolved_agenda_items(USER, ["shipped it"]) == 0


@pytest.mark.unit
class TestRetainAgendaSideEffects:
    async def test_closing_a_single_agenda_row_re_renders_the_page(
        self, boundaries: Boundaries
    ) -> None:
        # agenda.md is rendered from rows: a closed item stays on the page — and
        # in every prompt — until something re-renders it.
        open_row = make_row(content="ship the billing migration", category_path="agenda")
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(
            agenda_updates=[AgendaUpdate(item="ship the billing migration", resolved=True)]
        )
        boundaries.query_similar.return_value = [(str(open_row.id), 0.95)]
        boundaries.get_memories_by_ids.return_value = [open_row]

        await retain(
            USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
        )

        assert boundaries.render_agenda_document.await_args.args == (USER,)

    async def test_an_ingestion_that_touched_no_agenda_row_leaves_the_page_alone(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(
            facts=[make_fact("sam likes green tea")]
        )
        boundaries.reconcile.side_effect = lambda _user, facts, embeddings: [
            make_reconciled(fact, embedding=embedding) for fact, embedding in zip(facts, embeddings)
        ]

        await retain(
            USER, [{"role": "user", "content": "hi"}], source_type=MemorySourceType.CONVERSATION
        )

        boundaries.render_agenda_document.assert_not_awaited()

    async def test_the_agenda_stage_is_timed_on_the_wide_event(
        self, boundaries: Boundaries
    ) -> None:
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(
            facts=[make_fact("sam likes green tea")]
        )
        boundaries.reconcile.side_effect = lambda _user, facts, embeddings: [
            make_reconciled(fact, embedding=embedding) for fact, embedding in zip(facts, embeddings)
        ]

        async with captured_wide_event() as event:
            await retain(
                USER,
                [{"role": "user", "content": "hi"}],
                source_type=MemorySourceType.CONVERSATION,
            )

        assert "agenda_ms" in event["memory"]["timings"]


@pytest.mark.unit
class TestRetainFreePlanCap:
    """Passive ingestion admits only as many NEW facts as fit under the cap."""

    @staticmethod
    def _free_plan(*, cached_live: int, counted_live: int):
        """A FREE user whose Redis counter says one thing and Postgres another."""
        return (
            patch.object(
                ingestion.payment_service,
                "get_cached_plan_type",
                AsyncMock(return_value=PlanType.FREE),
            ),
            patch.object(
                ingestion.cap_counter,
                "get_cached_live_count",
                AsyncMock(return_value=cached_live),
            ),
            patch.object(
                ingestion.cap_counter, "set_cached_live_count", AsyncMock(return_value=None)
            ),
            patch.object(ingestion.cap_counter, "adjust_live_count", AsyncMock(return_value=None)),
            patch.object(
                ingestion.pg_store,
                "count_live_memories",
                AsyncMock(return_value=counted_live),
            ),
        )

    @staticmethod
    def _two_new_facts(boundaries: Boundaries) -> None:
        boundaries.extract_memories.return_value = ExtractedMemoryBatch(
            facts=[make_fact("fact a"), make_fact("fact b")]
        )
        boundaries.reconcile.side_effect = lambda _user, facts, embeddings: [
            make_reconciled(fact, embedding=embedding) for fact, embedding in zip(facts, embeddings)
        ]

    async def test_a_batch_that_clears_the_safety_margin_skips_the_count(
        self, boundaries: Boundaries
    ) -> None:
        # remaining == growth + margin exactly: the cached counter is trusted,
        # so no Postgres COUNT and both facts are admitted.
        self._two_new_facts(boundaries)
        cached_live = FREE_MEMORY_FACT_LIMIT - (2 + FREE_MEMORY_CAP_COUNT_SAFETY_MARGIN)
        counted, cached, seed, adjust, count = self._free_plan(
            cached_live=cached_live, counted_live=FREE_MEMORY_FACT_LIMIT
        )
        with counted, cached, seed, adjust, count as count_mock:
            await retain(
                USER,
                [{"role": "user", "content": "hi"}],
                source_type=MemorySourceType.CONVERSATION,
            )

        assert [record.content for record in boundaries.inserted_records] == ["fact a", "fact b"]
        count_mock.assert_not_awaited()

    async def test_a_batch_that_might_cross_the_cap_falls_back_to_the_exact_count(
        self, boundaries: Boundaries
    ) -> None:
        # One short of the margin: the counter is no longer trusted, the
        # authoritative COUNT says the user is at the cap, and nothing lands.
        self._two_new_facts(boundaries)
        cached_live = FREE_MEMORY_FACT_LIMIT - (1 + FREE_MEMORY_CAP_COUNT_SAFETY_MARGIN)
        counted, cached, seed, adjust, count = self._free_plan(
            cached_live=cached_live, counted_live=FREE_MEMORY_FACT_LIMIT
        )
        with counted, cached, seed, adjust, count as count_mock:
            await retain(
                USER,
                [{"role": "user", "content": "hi"}],
                source_type=MemorySourceType.CONVERSATION,
            )

        count_mock.assert_awaited_once()
        assert boundaries.inserted_records == []

    async def test_a_batch_crossing_the_cap_lands_exactly_at_it(
        self, boundaries: Boundaries
    ) -> None:
        self._two_new_facts(boundaries)
        counted, cached, seed, adjust, count = self._free_plan(
            cached_live=FREE_MEMORY_FACT_LIMIT, counted_live=FREE_MEMORY_FACT_LIMIT - 1
        )
        with counted, cached, seed, adjust, count:
            await retain(
                USER,
                [{"role": "user", "content": "hi"}],
                source_type=MemorySourceType.CONVERSATION,
            )

        # Facts keep reconciliation order, so the earlier one wins the last slot.
        assert [record.content for record in boundaries.inserted_records] == ["fact a"]


@pytest.mark.unit
class TestRetainSingleFreePlanCap:
    @staticmethod
    def _at_the_cap():
        return (
            patch.object(
                ingestion.payment_service,
                "get_cached_plan_type",
                AsyncMock(return_value=PlanType.FREE),
            ),
            patch.object(
                ingestion.cap_counter,
                "get_cached_live_count",
                AsyncMock(return_value=FREE_MEMORY_FACT_LIMIT),
            ),
            patch.object(
                ingestion.cap_counter, "set_cached_live_count", AsyncMock(return_value=None)
            ),
            patch.object(ingestion.cap_counter, "adjust_live_count", AsyncMock(return_value=None)),
            patch.object(
                ingestion.pg_store,
                "count_live_memories",
                AsyncMock(return_value=FREE_MEMORY_FACT_LIMIT),
            ),
        )

    async def test_a_new_fact_at_the_cap_fails_loud(self, boundaries: Boundaries) -> None:
        # Explicit adds fail loud so the tool can upsell; passive ingestion
        # drops silently.
        boundaries.reconcile.return_value = [make_reconciled(make_fact("sam likes green tea"))]

        plan, cached, seed, adjust, count = self._at_the_cap()
        with plan, cached, seed, adjust, count, pytest.raises(ingestion.MemoryLimitReachedError):
            await retain_single(
                USER,
                "sam likes green tea",
                category_path="preferences",
                source_type=MemorySourceType.MANUAL,
            )

        assert boundaries.inserted_records == []

    async def test_a_duplicate_at_the_cap_is_still_allowed(self, boundaries: Boundaries) -> None:
        # A DUPLICATE resolves to zero growth, so the cap has nothing to block.
        existing = make_row(content="sam likes green tea")
        boundaries.reconcile.return_value = [
            make_reconciled(
                make_fact("sam likes green tea"),
                ReconcileOutcome.DUPLICATE,
                target_memory_id=str(existing.id),
            )
        ]
        boundaries.get_memory.return_value = existing

        plan, cached, seed, adjust, count = self._at_the_cap()
        with (
            plan,
            cached,
            seed,
            adjust,
            count,
            patch.object(ingestion, "row_to_entry", return_value=MagicMock()) as row_to_entry,
        ):
            result = await retain_single(
                USER,
                "sam likes green tea",
                category_path="preferences",
                source_type=MemorySourceType.MANUAL,
            )

        assert result.outcome is ReconcileOutcome.DUPLICATE
        assert row_to_entry.call_args.args[0] is existing
