"""Unit tests for app.agents.tools.memory_tools.

The memory engine is mocked at the facade boundary; the payload shaping,
truncation, doc-type resolution and message formatting under test are real.
The ``memory_data`` payloads asserted here are the frontend tool-card contract
documented at the top of the module under test.
"""

from collections.abc import Iterator
from datetime import UTC, date as date_type, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.memory_tools import (
    _ADD_OUTCOMES,
    _cap,
    _document_payload,
    _entry_payload,
    _episode_payload,
    _format_entry_line,
    _hits_to_episode_payloads,
    _resolve_doc_type,
    _stream_memory_data,
    add_memory,
    forget_memory,
    get_journal,
    read_memory_document,
    search_conversations,
    search_journal,
    search_memory,
    tools,
    update_memory,
    update_memory_document,
)
from app.constants.memory import (
    MEMORY_DOC_FILENAMES,
    MEMORY_TOOL_CONTENT_MAX_CHARS,
    MEMORY_TOOL_DOCUMENT_MAX_CHARS,
    MemoryDocType,
    MemorySourceType,
    ReconcileOutcome,
)
from app.memory.management import MemoryNotFoundError
from app.memory.retrieval import EpisodeHit
from app.models.memory_models import (
    MemoryDocument,
    MemoryEntry,
    MemoryEpisode,
    MemoryEpisodeEntry,
    MemoryEpisodesResponse,
    MemorySearchResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.memory_tools"


def _make_config(user_id: str = FAKE_USER_ID) -> dict[str, Any]:
    """Return a minimal RunnableConfig-like dict with metadata.user_id."""
    return {"metadata": {"user_id": user_id}}


def _make_config_no_user() -> dict[str, Any]:
    """Config with no user_id to trigger auth errors."""
    return {"metadata": {}}


def _make_memory_entry(
    memory_id: str = "mem-1",
    content: str = "Test memory",
    score: float = 0.95,
) -> MemoryEntry:
    """Create a real MemoryEntry for use in test results."""
    return MemoryEntry(
        id=memory_id,
        content=content,
        relevance_score=score,
    )


def _make_document(
    doc_type: MemoryDocType = MemoryDocType.USER_MD,
    content: str = "# About the user\nLikes coffee.",
    version: int = 3,
) -> MemoryDocument:
    return MemoryDocument(
        doc_type=doc_type,
        content=content,
        version=version,
        updated_at=datetime(2026, 3, 12, 9, 30, tzinfo=UTC),
    )


@pytest.fixture
def stream() -> Iterator[MagicMock]:
    """Capture the ``memory_data`` events the tools emit to the frontend."""
    writer = MagicMock()
    with patch(f"{MODULE}.get_stream_writer", return_value=writer):
        yield writer


def _payloads(stream: MagicMock) -> list[dict[str, Any]]:
    return [call.args[0]["memory_data"] for call in stream.call_args_list]


# ---------------------------------------------------------------------------
# _stream_memory_data
# ---------------------------------------------------------------------------


class TestStreamMemoryData:
    def test_wraps_the_payload_under_the_registry_key(self, stream: MagicMock) -> None:
        _stream_memory_data({"action": "add"})
        stream.assert_called_once_with({"memory_data": {"action": "add"}})

    def test_outside_a_graph_run_it_is_a_silent_no_op(self) -> None:
        # Real langgraph raises RuntimeError here; a tool called from a script,
        # a worker or a test must not blow up because nobody is streaming.
        _stream_memory_data({"action": "add"})

    def test_a_non_runtime_error_is_not_swallowed(self) -> None:
        with (
            patch(f"{MODULE}.get_stream_writer", side_effect=ValueError("boom")),
            pytest.raises(ValueError),
        ):
            _stream_memory_data({"action": "add"})


# ---------------------------------------------------------------------------
# _cap
# ---------------------------------------------------------------------------


class TestCap:
    def test_text_at_the_limit_is_untouched(self) -> None:
        text = "x" * 10
        assert _cap(text, 10) == text

    def test_text_one_over_the_limit_is_truncated_to_exactly_the_limit(self) -> None:
        capped = _cap("x" * 11, 10)
        assert len(capped) == 10
        assert capped == "x" * 7 + "..."

    def test_empty_text_is_returned_as_is(self) -> None:
        assert _cap("", 10) == ""

    def test_unicode_is_truncated_by_character_not_byte(self) -> None:
        capped = _cap("é" * 11, 10)
        assert len(capped) == 10
        assert capped == "é" * 7 + "..."


# ---------------------------------------------------------------------------
# _entry_payload / _episode_payload / _document_payload
# ---------------------------------------------------------------------------


class TestEntryPayload:
    def test_serializes_json_mode_with_snake_case_keys(self) -> None:
        entry = MemoryEntry(id="mem-1", content="short", category_path="work/gaia")
        payload = _entry_payload(entry)
        assert payload["id"] == "mem-1"
        assert payload["category_path"] == "work/gaia"
        # mode="json" — datetimes/enums must already be JSON-native.
        assert payload["source_type"] == MemorySourceType.CONVERSATION.value

    def test_long_content_is_capped_for_the_frontend(self) -> None:
        entry = MemoryEntry(id="m", content="x" * (MEMORY_TOOL_CONTENT_MAX_CHARS + 50))
        payload = _entry_payload(entry)
        assert len(payload["content"]) == MEMORY_TOOL_CONTENT_MAX_CHARS
        assert payload["content"].endswith("...")

    def test_capping_does_not_mutate_the_source_entry(self) -> None:
        entry = MemoryEntry(id="m", content="x" * (MEMORY_TOOL_CONTENT_MAX_CHARS + 50))
        _entry_payload(entry)
        assert len(entry.content) == MEMORY_TOOL_CONTENT_MAX_CHARS + 50


class TestEpisodePayload:
    def test_maps_entries_and_summary(self) -> None:
        episode = MemoryEpisode(
            date="2026-03-12",
            entries=[MemoryEpisodeEntry(time="09:30", text="shipped", source="conversation")],
            summary="a good day",
        )
        assert _episode_payload(episode) == {
            "date": "2026-03-12",
            "entries": [{"time": "09:30", "text": "shipped", "source": "conversation"}],
            "summary": "a good day",
        }

    def test_absent_summary_stays_null(self) -> None:
        episode = MemoryEpisode(date="2026-03-12", entries=[], summary=None)
        assert _episode_payload(episode)["summary"] is None

    def test_long_entry_text_and_summary_are_capped(self) -> None:
        long = "x" * (MEMORY_TOOL_CONTENT_MAX_CHARS + 50)
        episode = MemoryEpisode(
            date="2026-03-12",
            entries=[MemoryEpisodeEntry(time="09:30", text=long, source="email")],
            summary=long,
        )
        payload = _episode_payload(episode)
        assert len(payload["entries"][0]["text"]) == MEMORY_TOOL_CONTENT_MAX_CHARS
        assert len(payload["summary"]) == MEMORY_TOOL_CONTENT_MAX_CHARS


class TestDocumentPayload:
    def test_serializes_the_document_contract(self) -> None:
        assert _document_payload(_make_document()) == {
            "doc_type": "user_md",
            "content": "# About the user\nLikes coffee.",
            "version": 3,
            "updated_at": "2026-03-12T09:30:00+00:00",
        }

    def test_content_uses_the_larger_document_cap(self) -> None:
        # A document must NOT be squeezed to the 400-char memory cap.
        content = "x" * (MEMORY_TOOL_CONTENT_MAX_CHARS + 100)
        payload = _document_payload(_make_document(content=content))
        assert payload["content"] == content

    def test_oversized_document_is_capped(self) -> None:
        content = "x" * (MEMORY_TOOL_DOCUMENT_MAX_CHARS + 10)
        payload = _document_payload(_make_document(content=content))
        assert len(payload["content"]) == MEMORY_TOOL_DOCUMENT_MAX_CHARS


# ---------------------------------------------------------------------------
# _hits_to_episode_payloads
# ---------------------------------------------------------------------------


class TestHitsToEpisodePayloads:
    def test_no_hits_produce_no_days(self) -> None:
        assert _hits_to_episode_payloads([]) == []

    def test_groups_hits_of_the_same_day_into_one_entry_list(self) -> None:
        day = date_type(2026, 3, 12)
        payloads = _hits_to_episode_payloads(
            [
                EpisodeHit(date=day, text="morning", time="09:30"),
                EpisodeHit(date=day, text="evening", time="18:00"),
            ]
        )
        assert len(payloads) == 1
        assert [entry["text"] for entry in payloads[0]["entries"]] == ["morning", "evening"]

    def test_a_timeless_hit_becomes_the_day_summary(self) -> None:
        day = date_type(2026, 3, 12)
        payloads = _hits_to_episode_payloads(
            [
                EpisodeHit(date=day, text="a quiet day", time=None),
                EpisodeHit(date=day, text="shipped", time="09:30"),
            ]
        )
        assert payloads[0]["summary"] == "a quiet day"
        assert [entry["text"] for entry in payloads[0]["entries"]] == ["shipped"]

    def test_days_are_returned_newest_first(self) -> None:
        payloads = _hits_to_episode_payloads(
            [
                EpisodeHit(date=date_type(2025, 1, 1), text="old", time="09:00"),
                EpisodeHit(date=date_type(2026, 3, 12), text="new", time="09:00"),
                EpisodeHit(date=date_type(2025, 6, 1), text="mid", time="09:00"),
            ]
        )
        assert [payload["date"] for payload in payloads] == [
            "2026-03-12",
            "2025-06-01",
            "2025-01-01",
        ]

    def test_dates_are_serialized_as_iso_strings(self) -> None:
        payloads = _hits_to_episode_payloads(
            [EpisodeHit(date=date_type(2026, 3, 12), text="t", time="09:00")]
        )
        assert payloads[0]["date"] == "2026-03-12"

    def test_long_hit_text_is_capped(self) -> None:
        long = "x" * (MEMORY_TOOL_CONTENT_MAX_CHARS + 50)
        payloads = _hits_to_episode_payloads(
            [EpisodeHit(date=date_type(2026, 3, 12), text=long, time="09:00")]
        )
        assert len(payloads[0]["entries"][0]["text"]) == MEMORY_TOOL_CONTENT_MAX_CHARS


# ---------------------------------------------------------------------------
# _format_entry_line
# ---------------------------------------------------------------------------


class TestFormatEntryLine:
    def test_includes_id_folder_date_and_score(self) -> None:
        entry = MemoryEntry(
            id="mem-1",
            content="Likes coffee",
            category_path="food",
            mentioned_at=datetime(2026, 3, 12, 9, 30, tzinfo=UTC),
            relevance_score=0.9512,
        )
        assert _format_entry_line(2, entry) == (
            "2. Likes coffee\n   (id: mem-1, folder: food, date: 2026-03-12, score: 0.95)"
        )

    def test_falls_back_to_created_at_when_never_mentioned(self) -> None:
        entry = MemoryEntry(
            id="mem-1",
            content="c",
            created_at=datetime(2025, 1, 2, tzinfo=UTC),
            relevance_score=None,
        )
        assert "date: 2025-01-02" in _format_entry_line(1, entry)

    def test_mentioned_at_wins_over_created_at(self) -> None:
        entry = MemoryEntry(
            id="mem-1",
            content="c",
            created_at=datetime(2025, 1, 2, tzinfo=UTC),
            mentioned_at=datetime(2026, 3, 12, tzinfo=UTC),
        )
        assert "date: 2026-03-12" in _format_entry_line(1, entry)

    def test_undated_entry_omits_the_date_field(self) -> None:
        entry = MemoryEntry(id="mem-1", content="c")
        line = _format_entry_line(1, entry)
        assert "date:" not in line

    def test_missing_score_omits_the_score_field(self) -> None:
        entry = MemoryEntry(id="mem-1", content="c", relevance_score=None)
        assert "score:" not in _format_entry_line(1, entry)

    def test_zero_score_is_still_rendered(self) -> None:
        # 0.0 is falsy — an `if entry.relevance_score:` check would drop it.
        entry = MemoryEntry(id="mem-1", content="c", relevance_score=0.0)
        assert "score: 0.00" in _format_entry_line(1, entry)


# ---------------------------------------------------------------------------
# _resolve_doc_type
# ---------------------------------------------------------------------------


class TestResolveDocType:
    @pytest.mark.parametrize("doc_type", list(MemoryDocType))
    def test_every_canonical_enum_value_resolves(self, doc_type: MemoryDocType) -> None:
        assert _resolve_doc_type(doc_type.value) is doc_type

    @pytest.mark.parametrize(
        ("filename", "doc_type"), [(name, kind) for kind, name in MEMORY_DOC_FILENAMES.items()]
    )
    def test_every_friendly_filename_resolves(self, filename: str, doc_type: MemoryDocType) -> None:
        assert _resolve_doc_type(filename.removesuffix(".md")) is doc_type
        assert _resolve_doc_type(filename) is doc_type

    @pytest.mark.parametrize("raw", ["  USER  ", "User.MD", "\tuser\n", "USER_MD"])
    def test_case_whitespace_and_extension_are_normalized(self, raw: str) -> None:
        assert _resolve_doc_type(raw) is MemoryDocType.USER_MD

    @pytest.mark.parametrize("raw", ["", "   ", "profile", "users", "user.txt", ".md"])
    def test_unknown_names_resolve_to_none(self, raw: str) -> None:
        assert _resolve_doc_type(raw) is None


# ---------------------------------------------------------------------------
# module wiring
# ---------------------------------------------------------------------------


class TestModuleWiring:
    def test_every_reconcile_outcome_has_a_frontend_label(self) -> None:
        # add_memory does an unguarded _ADD_OUTCOMES[outcome] lookup: a new
        # ReconcileOutcome without a label would KeyError at runtime.
        assert set(_ADD_OUTCOMES) == set(ReconcileOutcome)

    def test_exported_tool_list_matches_the_defined_tools(self) -> None:
        assert [tool.name for tool in tools] == [
            "add_memory",
            "search_memory",
            "update_memory",
            "forget_memory",
            "search_journal",
            "search_conversations",
            "get_journal",
            "read_memory_document",
            "update_memory_document",
        ]


# ---------------------------------------------------------------------------
# Tests: add_memory
# ---------------------------------------------------------------------------


class TestAddMemory:
    """Tests for the add_memory tool."""

    @staticmethod
    def _retained(entry: MemoryEntry, outcome: ReconcileOutcome) -> MagicMock:
        retained = MagicMock()
        retained.entry = entry
        retained.outcome = outcome
        return retained

    @patch(f"{MODULE}.memory_engine")
    async def test_happy_path(
        self,
        mock_engine: MagicMock,
    ) -> None:
        """Successful memory storage returns the ID and folder."""
        stored = MemoryEntry(
            id="mem-1",
            content="User likes coffee",
            category_path="food-preferences",
        )
        mock_engine.retain_single = AsyncMock(
            return_value=self._retained(stored, ReconcileOutcome.NEW)
        )

        result = await add_memory.coroutine(
            config=_make_config(),
            content="User likes coffee",
        )

        assert "mem-1" in result
        assert "food-preferences" in result
        mock_engine.retain_single.assert_awaited_once_with(
            FAKE_USER_ID,
            "User likes coffee",
            category_path=None,
            source_type=MemorySourceType.TOOL,
        )

    @patch(f"{MODULE}.memory_engine")
    async def test_explicit_folder_is_forwarded_to_the_engine(self, mock_engine: MagicMock) -> None:
        stored = MemoryEntry(id="mem-1", content="c", category_path="work/gaia")
        mock_engine.retain_single = AsyncMock(
            return_value=self._retained(stored, ReconcileOutcome.NEW)
        )

        await add_memory.coroutine(config=_make_config(), content="c", folder="work/gaia")

        assert mock_engine.retain_single.await_args.kwargs["category_path"] == "work/gaia"

    @pytest.mark.parametrize(
        ("outcome", "expected_label", "expected_phrase"),
        [
            (ReconcileOutcome.NEW, "new", "Memory stored under"),
            (ReconcileOutcome.UPDATES, "updated", "Updated an existing memory"),
            (ReconcileOutcome.EXTENDS, "extended", "extending a related memory"),
            (ReconcileOutcome.DUPLICATE, "duplicate", "Already known"),
        ],
    )
    @patch(f"{MODULE}.memory_engine")
    async def test_each_reconcile_outcome_has_its_own_message(
        self,
        mock_engine: MagicMock,
        outcome: ReconcileOutcome,
        expected_label: str,
        expected_phrase: str,
        stream: MagicMock,
    ) -> None:
        stored = MemoryEntry(id="mem-1", content="c", category_path="work")
        mock_engine.retain_single = AsyncMock(return_value=self._retained(stored, outcome))

        result = await add_memory.coroutine(config=_make_config(), content="c")

        assert expected_phrase in result
        payload = _payloads(stream)[0]
        assert payload["outcome"] == expected_label
        assert payload["message"] in result

    @patch(f"{MODULE}.memory_engine")
    async def test_streams_the_add_payload_contract(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        stored = MemoryEntry(id="mem-1", content="c", category_path="work/gaia")
        mock_engine.retain_single = AsyncMock(
            return_value=self._retained(stored, ReconcileOutcome.NEW)
        )

        await add_memory.coroutine(config=_make_config(), content="c")

        payload = _payloads(stream)[0]
        assert payload["action"] == "add"
        assert payload["folder"] == "work/gaia"
        assert [memory["id"] for memory in payload["memories"]] == ["mem-1"]

    async def test_no_user_id_returns_error(self) -> None:
        result = await add_memory.coroutine(
            config=_make_config_no_user(),
            content="data",
        )

        assert "user_id not found in config" in result

    async def test_no_config_returns_error(self) -> None:
        """Falsy config triggers the early guard."""
        # Empty dict {} is falsy; get_user_id_from_config returns "" → no user_id error
        result = await add_memory.coroutine(
            config={},
            content="data",
        )

        assert "user_id not found in config" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_missing_user_id_never_touches_the_engine(self, mock_engine: MagicMock) -> None:
        mock_engine.retain_single = AsyncMock()

        await add_memory.coroutine(config=_make_config_no_user(), content="data")

        mock_engine.retain_single.assert_not_awaited()

    @patch(f"{MODULE}.memory_engine")
    async def test_store_failure_returns_error_message(
        self,
        mock_engine: MagicMock,
    ) -> None:
        """When the engine raises an exception, tool returns a failure message."""
        mock_engine.retain_single = AsyncMock(side_effect=Exception("storage failed"))

        result = await add_memory.coroutine(
            config=_make_config(),
            content="data",
        )

        assert "Error storing memory" in result
        assert "storage failed" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_store_failure_streams_nothing_to_the_frontend(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.retain_single = AsyncMock(side_effect=RuntimeError("db down"))

        await add_memory.coroutine(config=_make_config(), content="data")

        stream.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: search_memory
# ---------------------------------------------------------------------------


class TestSearchMemory:
    """Tests for the search_memory tool."""

    @patch(f"{MODULE}.memory_engine")
    async def test_happy_path(
        self,
        mock_engine: MagicMock,
    ) -> None:
        """Successful search returns formatted results."""
        memories = [
            _make_memory_entry("mem-1", "Likes coffee", 0.95),
            _make_memory_entry("mem-2", "Works at ACME", 0.80),
        ]
        mock_engine.recall = AsyncMock(
            return_value=MemorySearchResult(memories=memories, total_count=2)
        )

        result = await search_memory.coroutine(
            config=_make_config(),
            query="coffee",
        )

        assert "Likes coffee" in result
        assert "Works at ACME" in result
        assert "0.95" in result
        mock_engine.recall.assert_awaited_once_with(
            FAKE_USER_ID, "coffee", limit=5, category_prefix=None
        )

    @patch(f"{MODULE}.memory_engine")
    async def test_custom_limit(
        self,
        mock_engine: MagicMock,
    ) -> None:
        """Custom limit is passed to service."""
        mock_engine.recall = AsyncMock(return_value=MemorySearchResult(memories=[], total_count=0))

        await search_memory.coroutine(
            config=_make_config(),
            query="anything",
            limit=10,
        )

        call_kwargs = mock_engine.recall.call_args.kwargs
        assert call_kwargs["limit"] == 10

    @patch(f"{MODULE}.memory_engine")
    async def test_zero_limit_falls_back_to_the_engine_default(
        self, mock_engine: MagicMock
    ) -> None:
        from app.constants.memory import DEFAULT_RECALL_LIMIT

        mock_engine.recall = AsyncMock(return_value=MemorySearchResult(memories=[], total_count=0))

        await search_memory.coroutine(config=_make_config(), query="q", limit=0)

        assert mock_engine.recall.await_args.kwargs["limit"] == DEFAULT_RECALL_LIMIT

    @patch(f"{MODULE}.memory_engine")
    async def test_no_results(
        self,
        mock_engine: MagicMock,
    ) -> None:
        """Empty search results returns appropriate message."""
        mock_engine.recall = AsyncMock(return_value=MemorySearchResult(memories=[], total_count=0))

        result = await search_memory.coroutine(
            config=_make_config(),
            query="nonexistent",
        )

        assert "No matching memories found" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_folder_scope_appears_in_the_message_and_the_query(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.recall = AsyncMock(return_value=MemorySearchResult(memories=[], total_count=0))

        result = await search_memory.coroutine(
            config=_make_config(), query="q", folder="relationships"
        )

        assert "in 'relationships'" in result
        assert mock_engine.recall.await_args.kwargs["category_prefix"] == "relationships"
        assert _payloads(stream)[0]["folder"] == "relationships"

    @patch(f"{MODULE}.memory_engine")
    async def test_streams_the_search_payload_contract(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.recall = AsyncMock(
            return_value=MemorySearchResult(
                memories=[_make_memory_entry("mem-1", "Likes coffee", 0.9)], total_count=1
            )
        )

        await search_memory.coroutine(config=_make_config(), query="coffee")

        payload = _payloads(stream)[0]
        assert payload["action"] == "search"
        assert payload["query"] == "coffee"
        assert payload["folder"] is None
        assert [memory["content"] for memory in payload["memories"]] == ["Likes coffee"]

    @patch(f"{MODULE}.memory_engine")
    async def test_empty_search_still_streams_an_event(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.recall = AsyncMock(return_value=MemorySearchResult(memories=[], total_count=0))

        await search_memory.coroutine(config=_make_config(), query="q")

        assert _payloads(stream)[0]["memories"] == []

    async def test_no_user_id_returns_error(self) -> None:
        result = await search_memory.coroutine(
            config=_make_config_no_user(),
            query="test",
        )

        assert "user_id not found in config" in result

    async def test_no_config_returns_error(self) -> None:
        # Empty dict {} is falsy; get_user_id_from_config returns "" → no user_id error
        result = await search_memory.coroutine(
            config={},
            query="test",
        )

        assert "user_id not found in config" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_engine_failure_propagates(self, mock_engine: MagicMock) -> None:
        # Unlike add_memory, a failed recall must NOT be reported to the model
        # as a plain string — a swallowed failure reads as "you have no
        # memories about that", which is a wrong answer, not a degraded one.
        mock_engine.recall = AsyncMock(side_effect=RuntimeError("chroma down"))

        with pytest.raises(RuntimeError, match="chroma down"):
            await search_memory.coroutine(config=_make_config(), query="q")

    @patch(f"{MODULE}.memory_engine")
    async def test_memory_without_score_omits_score(
        self,
        mock_engine: MagicMock,
    ) -> None:
        """Memories without relevance_score don't show score in output."""
        memory = MemoryEntry(
            id="mem-1",
            content="No score memory",
            relevance_score=None,
        )
        mock_engine.recall = AsyncMock(
            return_value=MemorySearchResult(memories=[memory], total_count=1)
        )

        result = await search_memory.coroutine(
            config=_make_config(),
            query="test",
        )

        assert "No score memory" in result
        assert "score:" not in result

    @patch(f"{MODULE}.memory_engine")
    async def test_multiple_results_numbered(
        self,
        mock_engine: MagicMock,
    ) -> None:
        """Results are numbered sequentially in the output."""
        memories = [
            _make_memory_entry("m1", "First", 0.9),
            _make_memory_entry("m2", "Second", 0.8),
            _make_memory_entry("m3", "Third", 0.7),
        ]
        mock_engine.recall = AsyncMock(
            return_value=MemorySearchResult(memories=memories, total_count=3)
        )

        result = await search_memory.coroutine(
            config=_make_config(),
            query="all",
        )

        assert "1." in result
        assert "2." in result
        assert "3." in result


# ---------------------------------------------------------------------------
# Tests: update_memory
# ---------------------------------------------------------------------------


class TestUpdateMemory:
    @patch(f"{MODULE}.memory_engine")
    async def test_returns_the_new_version_and_id(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        updated = MemoryEntry(id="mem-2", content="new", category_path="home", version=2)
        mock_engine.update_memory = AsyncMock(return_value=updated)

        result = await update_memory.coroutine(
            config=_make_config(), memory_id="mem-1", new_content="new"
        )

        assert "v2" in result
        assert "home" in result
        assert "New ID: mem-2" in result
        mock_engine.update_memory.assert_awaited_once_with(FAKE_USER_ID, "mem-1", "new")

    @patch(f"{MODULE}.memory_engine")
    async def test_streams_the_update_payload_contract(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        updated = MemoryEntry(id="mem-2", content="new", version=2)
        mock_engine.update_memory = AsyncMock(return_value=updated)

        await update_memory.coroutine(config=_make_config(), memory_id="mem-1", new_content="new")

        payload = _payloads(stream)[0]
        assert payload["action"] == "update"
        assert [memory["id"] for memory in payload["memories"]] == ["mem-2"]

    @patch(f"{MODULE}.memory_engine")
    async def test_an_unknown_id_raises_instead_of_returning_a_readable_error(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        # An error STRING reads back to the model as an ordinary tool result:
        # it typo'd an id, saw "Error: ... not found", and told the user the
        # memory had been corrected. Raising is what stops that.
        mock_engine.update_memory = AsyncMock(side_effect=MemoryNotFoundError("gone"))

        with pytest.raises(MemoryNotFoundError):
            await update_memory.coroutine(
                config=_make_config(), memory_id="gone", new_content="new"
            )

        stream.assert_not_called()

    async def test_missing_user_id_returns_error(self) -> None:
        result = await update_memory.coroutine(
            config=_make_config_no_user(), memory_id="m", new_content="c"
        )
        assert "user_id not found in config" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_engine_failure_propagates(self, mock_engine: MagicMock) -> None:
        mock_engine.update_memory = AsyncMock(side_effect=RuntimeError("pg down"))

        with pytest.raises(RuntimeError, match="pg down"):
            await update_memory.coroutine(config=_make_config(), memory_id="m", new_content="c")


# ---------------------------------------------------------------------------
# Tests: forget_memory
# ---------------------------------------------------------------------------


class TestForgetMemory:
    @patch(f"{MODULE}.memory_engine")
    async def test_confirms_the_id_and_reason(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.forget_memory = AsyncMock(return_value=True)

        result = await forget_memory.coroutine(
            config=_make_config(), memory_id="mem-1", reason="user moved"
        )

        assert "mem-1" in result
        assert "user moved" in result
        mock_engine.forget_memory.assert_awaited_once_with(FAKE_USER_ID, "mem-1", "user moved")

    @patch(f"{MODULE}.memory_engine")
    async def test_streams_the_forget_payload_contract(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.forget_memory = AsyncMock(return_value=True)

        await forget_memory.coroutine(config=_make_config(), memory_id="mem-1", reason="outdated")

        assert _payloads(stream)[0] == {
            "action": "forget",
            "memory_id": "mem-1",
            "reason": "outdated",
            "message": "Memory forgotten",
        }

    @patch(f"{MODULE}.memory_engine")
    async def test_unknown_id_reports_not_found_without_streaming(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.forget_memory = AsyncMock(return_value=False)

        result = await forget_memory.coroutine(config=_make_config(), memory_id="gone", reason="r")

        assert result == "Error: memory gone not found."
        stream.assert_not_called()

    async def test_missing_user_id_returns_error(self) -> None:
        result = await forget_memory.coroutine(
            config=_make_config_no_user(), memory_id="m", reason="r"
        )
        assert "user_id not found in config" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_engine_failure_propagates(self, mock_engine: MagicMock) -> None:
        mock_engine.forget_memory = AsyncMock(side_effect=RuntimeError("pg down"))

        with pytest.raises(RuntimeError, match="pg down"):
            await forget_memory.coroutine(config=_make_config(), memory_id="m", reason="r")


# ---------------------------------------------------------------------------
# Tests: search_journal
# ---------------------------------------------------------------------------


class TestSearchJournal:
    @patch(f"{MODULE}.memory_engine")
    async def test_renders_entry_hits_with_their_time(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.recall_episodes = AsyncMock(
            return_value=[
                EpisodeHit(date=date_type(2026, 3, 12), text="shipped the API", time="09:30")
            ]
        )

        result = await search_journal.coroutine(config=_make_config(), query="shipped")

        assert "- 2026-03-12 09:30: shipped the API" in result
        mock_engine.recall_episodes.assert_awaited_once_with(FAKE_USER_ID, "shipped")

    @patch(f"{MODULE}.memory_engine")
    async def test_timeless_hit_is_labelled_a_day_summary(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.recall_episodes = AsyncMock(
            return_value=[EpisodeHit(date=date_type(2026, 3, 12), text="a quiet day", time=None)]
        )

        result = await search_journal.coroutine(config=_make_config(), query="quiet")

        assert "- 2026-03-12 (day summary): a quiet day" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_day_count_reflects_distinct_days_not_hits(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        day = date_type(2026, 3, 12)
        mock_engine.recall_episodes = AsyncMock(
            return_value=[
                EpisodeHit(date=day, text="a", time="09:00"),
                EpisodeHit(date=day, text="b", time="18:00"),
            ]
        )

        result = await search_journal.coroutine(config=_make_config(), query="q")

        assert "Found journal activity on 1 days" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_streams_the_journal_payload_contract(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.recall_episodes = AsyncMock(
            return_value=[EpisodeHit(date=date_type(2026, 3, 12), text="shipped", time="09:30")]
        )

        await search_journal.coroutine(config=_make_config(), query="shipped")

        payload = _payloads(stream)[0]
        assert payload["action"] == "journal"
        assert payload["query"] == "shipped"
        assert payload["episodes"][0]["date"] == "2026-03-12"

    @patch(f"{MODULE}.memory_engine")
    async def test_no_hits_reports_the_query_back(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.recall_episodes = AsyncMock(return_value=[])

        result = await search_journal.coroutine(config=_make_config(), query="nothing")

        assert result == "No journal entries matching 'nothing'."
        assert _payloads(stream)[0]["episodes"] == []

    async def test_missing_user_id_returns_error(self) -> None:
        result = await search_journal.coroutine(config=_make_config_no_user(), query="q")
        assert "user_id not found in config" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_engine_failure_propagates(self, mock_engine: MagicMock) -> None:
        mock_engine.recall_episodes = AsyncMock(side_effect=RuntimeError("pg down"))

        with pytest.raises(RuntimeError, match="pg down"):
            await search_journal.coroutine(config=_make_config(), query="q")


# ---------------------------------------------------------------------------
# Tests: search_conversations
# ---------------------------------------------------------------------------


class TestSearchConversations:
    @patch(f"{MODULE}.memory_engine")
    async def test_renders_each_passage_with_date_and_score(self, mock_engine: MagicMock) -> None:
        mock_engine.recall_transcripts = AsyncMock(
            return_value=[("2026-03-12", "the exact passage", 0.9123)]
        )

        result = await search_conversations.coroutine(config=_make_config(), query="passage")

        assert "[2026-03-12] (match 0.91)" in result
        assert "the exact passage" in result
        mock_engine.recall_transcripts.assert_awaited_once_with(FAKE_USER_ID, "passage")

    @patch(f"{MODULE}.memory_engine")
    async def test_long_passages_are_capped_at_the_document_limit(
        self, mock_engine: MagicMock
    ) -> None:
        long = "x" * (MEMORY_TOOL_DOCUMENT_MAX_CHARS + 100)
        mock_engine.recall_transcripts = AsyncMock(return_value=[("2026-03-12", long, 0.9)])

        result = await search_conversations.coroutine(config=_make_config(), query="q")

        assert "x" * MEMORY_TOOL_DOCUMENT_MAX_CHARS not in result
        assert result.endswith("...")

    @patch(f"{MODULE}.memory_engine")
    async def test_multiple_passages_are_separated(self, mock_engine: MagicMock) -> None:
        mock_engine.recall_transcripts = AsyncMock(
            return_value=[("2026-03-12", "first", 0.9), ("2025-01-01", "second", 0.5)]
        )

        result = await search_conversations.coroutine(config=_make_config(), query="q")

        assert "first" in result
        assert "second" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_no_hits_reports_the_query_back(self, mock_engine: MagicMock) -> None:
        mock_engine.recall_transcripts = AsyncMock(return_value=[])

        result = await search_conversations.coroutine(config=_make_config(), query="nothing")

        assert result == "No past-conversation passages matching 'nothing'."

    @patch(f"{MODULE}.memory_engine")
    async def test_never_streams_a_tool_card(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        # search_conversations is deliberately absent from the memory_data
        # contract — raw transcript text must not be pushed to the tool card.
        mock_engine.recall_transcripts = AsyncMock(return_value=[("2026-03-12", "text", 0.9)])

        await search_conversations.coroutine(config=_make_config(), query="q")

        stream.assert_not_called()

    async def test_missing_user_id_returns_error(self) -> None:
        result = await search_conversations.coroutine(config=_make_config_no_user(), query="q")
        assert "user_id not found in config" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_engine_failure_propagates(self, mock_engine: MagicMock) -> None:
        mock_engine.recall_transcripts = AsyncMock(side_effect=RuntimeError("chroma down"))

        with pytest.raises(RuntimeError, match="chroma down"):
            await search_conversations.coroutine(config=_make_config(), query="q")


# ---------------------------------------------------------------------------
# Tests: get_journal
# ---------------------------------------------------------------------------


class TestGetJournal:
    @staticmethod
    def _response(episode: MemoryEpisode | None) -> MemoryEpisodesResponse:
        return MemoryEpisodesResponse(episodes=[episode] if episode else [])

    @patch(f"{MODULE}.memory_engine")
    async def test_renders_summary_and_entries_for_the_day(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        episode = MemoryEpisode(
            date="2026-03-12",
            entries=[
                MemoryEpisodeEntry(time="09:30", text="shipped", source="conversation"),
                MemoryEpisodeEntry(time="18:00", text="gym", source="conversation"),
            ],
            summary="a productive day",
        )
        mock_engine.get_episodes = AsyncMock(return_value=self._response(episode))

        result = await get_journal.coroutine(config=_make_config(), date="2026-03-12")

        assert "Journal for 2026-03-12 (2 entries)" in result
        assert "Summary: a productive day" in result
        assert "- 09:30 shipped" in result
        assert "- 18:00 gym" in result
        mock_engine.get_episodes.assert_awaited_once_with(
            FAKE_USER_ID, date_type(2026, 3, 12), date_type(2026, 3, 12)
        )

    @patch(f"{MODULE}.memory_engine")
    async def test_summary_only_day_is_rendered_without_entry_lines(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        episode = MemoryEpisode(date="2026-03-12", entries=[], summary="a quiet day")
        mock_engine.get_episodes = AsyncMock(return_value=self._response(episode))

        result = await get_journal.coroutine(config=_make_config(), date="2026-03-12")

        assert "Summary: a quiet day" in result
        assert "(0 entries)" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_entries_without_a_summary_omit_the_summary_line(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        episode = MemoryEpisode(
            date="2026-03-12",
            entries=[MemoryEpisodeEntry(time="09:30", text="shipped", source="conversation")],
            summary=None,
        )
        mock_engine.get_episodes = AsyncMock(return_value=self._response(episode))

        result = await get_journal.coroutine(config=_make_config(), date="2026-03-12")

        assert "Summary:" not in result
        assert "- 09:30 shipped" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_streams_the_journal_payload_for_a_populated_day(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        episode = MemoryEpisode(
            date="2026-03-12",
            entries=[MemoryEpisodeEntry(time="09:30", text="shipped", source="conversation")],
            summary=None,
        )
        mock_engine.get_episodes = AsyncMock(return_value=self._response(episode))

        await get_journal.coroutine(config=_make_config(), date="2026-03-12")

        payload = _payloads(stream)[0]
        assert payload["action"] == "journal"
        assert payload["query"] is None
        assert payload["episodes"][0]["entries"][0]["text"] == "shipped"

    @patch(f"{MODULE}.memory_engine")
    async def test_empty_day_streams_an_empty_episode_list(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.get_episodes = AsyncMock(return_value=self._response(None))

        result = await get_journal.coroutine(config=_make_config(), date="2026-03-12")

        assert result == "No journal entries for 2026-03-12."
        assert _payloads(stream)[0]["episodes"] == []

    @patch(f"{MODULE}.memory_engine")
    async def test_day_row_with_neither_entries_nor_summary_counts_as_empty(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        episode = MemoryEpisode(date="2026-03-12", entries=[], summary=None)
        mock_engine.get_episodes = AsyncMock(return_value=self._response(episode))

        result = await get_journal.coroutine(config=_make_config(), date="2026-03-12")

        assert result == "No journal entries for 2026-03-12."

    @pytest.mark.parametrize(
        "bad_date", ["12/03/2026", "March 12", "2026-13-45", "", "2026-03-12T09:30:00"]
    )
    @patch(f"{MODULE}.memory_engine")
    async def test_unparseable_date_is_rejected_before_any_query(
        self, mock_engine: MagicMock, bad_date: str
    ) -> None:
        mock_engine.get_episodes = AsyncMock()

        result = await get_journal.coroutine(config=_make_config(), date=bad_date)

        assert f"Error: invalid date '{bad_date}'" in result
        assert "YYYY-MM-DD" in result
        mock_engine.get_episodes.assert_not_awaited()

    async def test_missing_user_id_returns_error(self) -> None:
        result = await get_journal.coroutine(config=_make_config_no_user(), date="2026-03-12")
        assert "user_id not found in config" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_engine_failure_propagates(self, mock_engine: MagicMock) -> None:
        mock_engine.get_episodes = AsyncMock(side_effect=RuntimeError("pg down"))

        with pytest.raises(RuntimeError, match="pg down"):
            await get_journal.coroutine(config=_make_config(), date="2026-03-12")


# ---------------------------------------------------------------------------
# Tests: read_memory_document
# ---------------------------------------------------------------------------


class TestReadMemoryDocument:
    @patch(f"{MODULE}.memory_engine")
    async def test_returns_the_full_uncapped_content_to_the_agent(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        # The agent gets the whole document; only the streamed tool card is
        # capped, so a long user.md is not silently truncated mid-reasoning.
        content = "y" * (MEMORY_TOOL_DOCUMENT_MAX_CHARS + 100)
        mock_engine.get_document = AsyncMock(return_value=_make_document(content=content))

        result = await read_memory_document.coroutine(config=_make_config(), doc_type="user")

        assert result == content
        assert len(_payloads(stream)[0]["document"]["content"]) == MEMORY_TOOL_DOCUMENT_MAX_CHARS

    @patch(f"{MODULE}.memory_engine")
    async def test_resolves_a_friendly_name_to_the_canonical_doc_type(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.get_document = AsyncMock(
            return_value=_make_document(doc_type=MemoryDocType.PEOPLE_MD)
        )

        await read_memory_document.coroutine(config=_make_config(), doc_type="  People.md ")

        mock_engine.get_document.assert_awaited_once_with(FAKE_USER_ID, MemoryDocType.PEOPLE_MD)

    @patch(f"{MODULE}.memory_engine")
    async def test_streams_the_document_payload_marked_not_updated(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.get_document = AsyncMock(return_value=_make_document())

        await read_memory_document.coroutine(config=_make_config(), doc_type="user")

        payload = _payloads(stream)[0]
        assert payload["action"] == "document"
        assert payload["updated"] is False
        assert payload["document"]["doc_type"] == "user_md"
        assert "v3" in payload["message"]

    @patch(f"{MODULE}.memory_engine")
    async def test_missing_document_explains_it_fills_in_automatically(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.get_document = AsyncMock(return_value=None)

        result = await read_memory_document.coroutine(config=_make_config(), doc_type="agenda")

        assert "The 'agenda' document is empty" in result
        stream.assert_not_called()

    @pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
    @patch(f"{MODULE}.memory_engine")
    async def test_whitespace_only_document_counts_as_empty(
        self, mock_engine: MagicMock, blank: str, stream: MagicMock
    ) -> None:
        mock_engine.get_document = AsyncMock(return_value=_make_document(content=blank))

        result = await read_memory_document.coroutine(config=_make_config(), doc_type="user")

        assert "is empty" in result
        stream.assert_not_called()

    @patch(f"{MODULE}.memory_engine")
    async def test_unknown_doc_type_lists_the_valid_choices(self, mock_engine: MagicMock) -> None:
        mock_engine.get_document = AsyncMock()

        result = await read_memory_document.coroutine(config=_make_config(), doc_type="diary")

        assert "unknown document 'diary'" in result
        for filename in MEMORY_DOC_FILENAMES.values():
            assert filename.removesuffix(".md") in result
        mock_engine.get_document.assert_not_awaited()

    async def test_missing_user_id_returns_error(self) -> None:
        result = await read_memory_document.coroutine(
            config=_make_config_no_user(), doc_type="user"
        )
        assert "user_id not found in config" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_engine_failure_propagates(self, mock_engine: MagicMock) -> None:
        mock_engine.get_document = AsyncMock(side_effect=RuntimeError("pg down"))

        with pytest.raises(RuntimeError, match="pg down"):
            await read_memory_document.coroutine(config=_make_config(), doc_type="user")


# ---------------------------------------------------------------------------
# Tests: update_memory_document
# ---------------------------------------------------------------------------


class TestUpdateMemoryDocument:
    @patch(f"{MODULE}.memory_engine")
    async def test_reports_the_new_version_and_the_replace_semantics(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.update_document = AsyncMock(return_value=_make_document(version=4))

        result = await update_memory_document.coroutine(
            config=_make_config(), doc_type="user", content="# New"
        )

        assert "Rewrote the 'user' memory document (now v4)" in result
        assert "full content was replaced" in result
        mock_engine.update_document.assert_awaited_once_with(
            FAKE_USER_ID, MemoryDocType.USER_MD, "# New"
        )

    @patch(f"{MODULE}.memory_engine")
    async def test_streams_the_document_payload_marked_updated(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.update_document = AsyncMock(
            return_value=_make_document(doc_type=MemoryDocType.PEOPLE_MD, version=2)
        )

        await update_memory_document.coroutine(
            config=_make_config(), doc_type="people", content="# New"
        )

        payload = _payloads(stream)[0]
        assert payload["action"] == "document"
        assert payload["updated"] is True
        assert payload["document"]["doc_type"] == "people_md"
        assert payload["document"]["version"] == 2

    @patch(f"{MODULE}.memory_engine")
    async def test_empty_content_is_a_legitimate_full_replace(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.update_document = AsyncMock(return_value=_make_document(content="", version=5))

        result = await update_memory_document.coroutine(
            config=_make_config(), doc_type="user", content=""
        )

        assert "now v5" in result
        assert mock_engine.update_document.await_args.args[2] == ""

    @patch(f"{MODULE}.memory_engine")
    async def test_unknown_doc_type_is_rejected_before_any_write(
        self, mock_engine: MagicMock
    ) -> None:
        mock_engine.update_document = AsyncMock()

        result = await update_memory_document.coroutine(
            config=_make_config(), doc_type="scratchpad", content="# New"
        )

        assert "unknown document 'scratchpad'" in result
        mock_engine.update_document.assert_not_awaited()

    async def test_missing_user_id_returns_error(self) -> None:
        result = await update_memory_document.coroutine(
            config=_make_config_no_user(), doc_type="user", content="c"
        )
        assert "user_id not found in config" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_engine_failure_propagates(self, mock_engine: MagicMock) -> None:
        mock_engine.update_document = AsyncMock(side_effect=RuntimeError("pg down"))

        with pytest.raises(RuntimeError, match="pg down"):
            await update_memory_document.coroutine(
                config=_make_config(), doc_type="user", content="c"
            )
