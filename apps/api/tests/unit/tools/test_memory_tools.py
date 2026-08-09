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
    FREE_MEMORY_FACT_LIMIT,
    MEMORY_DOC_FILENAMES,
    MEMORY_TOOL_CONTENT_MAX_CHARS,
    MEMORY_TOOL_DOCUMENT_MAX_CHARS,
    MemoryDocType,
    MemorySourceType,
    ReconcileOutcome,
)
from app.memory.ingestion import MemoryLimitReachedError
from app.memory.retrieval import EpisodeHit
from app.models.memory_models import (
    MemoryDocument,
    MemoryEntry,
    MemoryEpisode,
    MemoryEpisodeEntry,
    MemoryEpisodesResponse,
    MemorySearchResult,
)
from app.models.payment_models import PlanType
from shared.py.wide_events import MemoryContext, UserContext

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


@pytest.fixture
def log() -> Iterator[MagicMock]:
    """Capture the wide-event log lines the tools emit (success, failure, warning)."""
    logger = MagicMock()
    with patch(f"{MODULE}.log", logger):
        yield logger


def _payloads(stream: MagicMock) -> list[dict[str, Any]]:
    return [call.args[0]["memory_data"] for call in stream.call_args_list]


def _serialized_entry(entry: MemoryEntry) -> dict[str, Any]:
    """The exact ``model_dump(mode="json")`` a payload carries for a short entry."""
    return entry.model_dump(mode="json")


def _assert_success_log(log: MagicMock, memory: MemoryContext) -> None:
    """Assert the canonical success wide-event for a tool run."""
    log.set.assert_called_once_with(user=UserContext(id=FAKE_USER_ID), memory=memory)


def _assert_failure_logged(
    log: MagicMock, operation: str, error_type: str, error: str
) -> None:
    """Assert the canonical failure wide-event pair (error + failed set)."""
    log.error.assert_called_once_with(
        "memory_tool_failed",
        operation=operation,
        error_type=error_type,
        error=error,
    )
    log.set.assert_called_once_with(memory=MemoryContext(operation=operation, success=False))


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

    def test_json_mode_serializes_datetimes_and_enums_as_json_natives(self) -> None:
        # mode="json" is the contract: datetimes become ISO strings and enums
        # their values — a python-mode dump would leak datetime objects into
        # the frontend payload and break the tool card.
        entry = MemoryEntry(
            id="mem-1",
            content="c",
            mentioned_at=datetime(2026, 3, 12, 9, 30, tzinfo=UTC),
            created_at=datetime(2025, 1, 2, tzinfo=UTC),
            occurred_start=datetime(2026, 3, 12, 9, 0, tzinfo=UTC),
            occurred_end=datetime(2026, 3, 12, 11, 0, tzinfo=UTC),
        )
        payload = _entry_payload(entry)
        assert payload["mentioned_at"] == "2026-03-12T09:30:00Z"
        assert payload["created_at"] == "2025-01-02T00:00:00Z"
        assert payload["occurred_start"] == "2026-03-12T09:00:00Z"
        assert payload["occurred_end"] == "2026-03-12T11:00:00Z"
        assert payload["kind"] == "fact"
        assert payload["is_latest"] is True


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

    def test_a_day_of_only_timed_hits_still_carries_the_null_summary_key(self) -> None:
        day = date_type(2026, 3, 12)
        payloads = _hits_to_episode_payloads(
            [EpisodeHit(date=day, text="morning", time="09:30")]
        )
        assert payloads[0]["summary"] is None

    def test_timed_hits_keep_their_time_and_a_null_source(self) -> None:
        day = date_type(2026, 3, 12)
        payloads = _hits_to_episode_payloads(
            [EpisodeHit(date=day, text="morning", time="09:30")]
        )
        entry = payloads[0]["entries"][0]
        assert entry["time"] == "09:30"
        assert entry["source"] is None


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
        stream: MagicMock,
        log: MagicMock,
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

        assert result == "Memory stored under 'food-preferences' (ID: mem-1)"
        mock_engine.retain_single.assert_awaited_once_with(
            FAKE_USER_ID,
            "User likes coffee",
            category_path=None,
            source_type=MemorySourceType.TOOL,
        )
        _assert_success_log(
            log,
            memory=MemoryContext(
                operation="create",
                success=True,
                memory_id="mem-1",
                content_length=17,
            ),
        )
        assert _payloads(stream)[0] == {
            "action": "add",
            "memories": [_serialized_entry(stored)],
            "folder": "food-preferences",
            "outcome": "new",
            "message": "Memory stored under 'food-preferences'",
        }

    @patch(f"{MODULE}.memory_engine")
    async def test_explicit_folder_is_forwarded_to_the_engine(self, mock_engine: MagicMock) -> None:
        stored = MemoryEntry(id="mem-1", content="c", category_path="work/gaia")
        mock_engine.retain_single = AsyncMock(
            return_value=self._retained(stored, ReconcileOutcome.NEW)
        )

        await add_memory.coroutine(config=_make_config(), content="c", folder="work/gaia")

        assert mock_engine.retain_single.await_args.kwargs["category_path"] == "work/gaia"

    @pytest.mark.parametrize(
        ("outcome", "expected_label", "expected_message"),
        [
            (ReconcileOutcome.NEW, "new", "Memory stored under 'work'"),
            (ReconcileOutcome.UPDATES, "updated", "Updated an existing memory under 'work'"),
            (
                ReconcileOutcome.EXTENDS,
                "extended",
                "Stored under 'work', extending a related memory",
            ),
            (
                ReconcileOutcome.DUPLICATE,
                "duplicate",
                "Already known — matched an existing memory under 'work'",
            ),
        ],
    )
    @patch(f"{MODULE}.memory_engine")
    async def test_each_reconcile_outcome_has_its_own_message(
        self,
        mock_engine: MagicMock,
        outcome: ReconcileOutcome,
        expected_label: str,
        expected_message: str,
        stream: MagicMock,
        log: MagicMock,
    ) -> None:
        stored = MemoryEntry(id="mem-1", content="c", category_path="work")
        mock_engine.retain_single = AsyncMock(return_value=self._retained(stored, outcome))

        result = await add_memory.coroutine(config=_make_config(), content="c")

        assert result == f"{expected_message} (ID: mem-1)"
        assert _payloads(stream)[0] == {
            "action": "add",
            "memories": [_serialized_entry(stored)],
            "folder": "work",
            "outcome": expected_label,
            "message": expected_message,
        }
        _assert_success_log(
            log,
            memory=MemoryContext(
                operation="create", success=True, memory_id="mem-1", content_length=1
            ),
        )

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
    async def test_cap_reached_fails_loud_with_the_upgrade_card(
        self, mock_engine: MagicMock, stream: MagicMock, log: MagicMock
    ) -> None:
        mock_engine.retain_single = AsyncMock(
            side_effect=MemoryLimitReachedError(limit=12)
        )

        result = await add_memory.coroutine(config=_make_config(), content="data")

        assert result == (
            "Memory limit reached: the free plan stores up to 12 memories, "
            "and this user's memory is full. The new fact was NOT saved. Tell the "
            "user their saved memories are full and that upgrading to Pro unlocks "
            "unlimited memories (existing memories still work)."
        )
        log.info.assert_called_once_with(
            "memory_cap_reached",
            event_name="memory_cap_reached",
            user_id=FAKE_USER_ID,
            source="add_memory_tool",
            limit=12,
        )
        log.set.assert_called_once_with(
            memory=MemoryContext(operation="create", success=False)
        )
        card = stream.call_args.args[0]["tool_data"]
        assert card["tool_name"] == "rate_limit_data"
        assert card["tool_category"] == "system"
        assert card["data"] == {
            "feature": "memory",
            "plan_required": PlanType.PRO.value,
            "reset_time": None,
            "current_plan": PlanType.FREE.value,
            "message": (
                f"Your free plan stores up to {FREE_MEMORY_FACT_LIMIT} "
                "memories and they are all used. Everything already "
                "saved keeps working. Upgrade to Pro for unlimited "
                "memories."
            ),
        }
        assert isinstance(card["timestamp"], str)
        # The card timestamp must be tz-aware UTC — a naive local-time stamp
        # (datetime.now() without tz) is the exact bug this assertion pins.
        assert datetime.fromisoformat(card["timestamp"]).tzinfo == UTC

    @patch(f"{MODULE}.memory_engine")
    async def test_store_failure_returns_error_message(
        self,
        mock_engine: MagicMock,
        log: MagicMock,
    ) -> None:
        """When the engine raises an exception, tool returns a failure message."""
        mock_engine.retain_single = AsyncMock(side_effect=Exception("storage failed"))

        result = await add_memory.coroutine(
            config=_make_config(),
            content="data",
        )

        assert result == "Error storing memory: storage failed"
        _assert_failure_logged(log, "create", "Exception", "storage failed")

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
        stream: MagicMock,
        log: MagicMock,
    ) -> None:
        """Successful search returns formatted results."""
        memories = [
            MemoryEntry(
                id="mem-1",
                content="Likes coffee",
                category_path="food",
                relevance_score=0.95,
            ),
            MemoryEntry(
                id="mem-2",
                content="Works at ACME",
                category_path="work",
                relevance_score=0.80,
            ),
        ]
        mock_engine.recall = AsyncMock(
            return_value=MemorySearchResult(memories=memories, total_count=2)
        )

        result = await search_memory.coroutine(
            config=_make_config(),
            query="coffee",
        )

        assert result == (
            "Found 2 memories:\n\n"
            "1. Likes coffee\n   (id: mem-1, folder: food, score: 0.95)\n"
            "2. Works at ACME\n   (id: mem-2, folder: work, score: 0.80)"
        )
        mock_engine.recall.assert_awaited_once_with(
            FAKE_USER_ID, "coffee", limit=5, category_prefix=None
        )
        _assert_success_log(
            log,
            memory=MemoryContext(
                operation="recall", success=True, query="coffee", result_count=2
            ),
        )
        assert _payloads(stream)[0] == {
            "action": "search",
            "query": "coffee",
            "folder": None,
            "memories": [_serialized_entry(m) for m in memories],
            "message": "Found 2 memories",
        }

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
        stream: MagicMock,
        log: MagicMock,
    ) -> None:
        """Empty search results returns appropriate message."""
        mock_engine.recall = AsyncMock(return_value=MemorySearchResult(memories=[], total_count=0))

        result = await search_memory.coroutine(
            config=_make_config(),
            query="nonexistent",
        )

        assert result == "No matching memories found."
        assert _payloads(stream)[0] == {
            "action": "search",
            "query": "nonexistent",
            "folder": None,
            "memories": [],
            "message": "No matching memories",
        }
        _assert_success_log(
            log,
            memory=MemoryContext(
                operation="recall", success=True, query="nonexistent", result_count=0
            ),
        )

    @patch(f"{MODULE}.memory_engine")
    async def test_folder_scope_appears_in_the_message_and_the_query(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.recall = AsyncMock(return_value=MemorySearchResult(memories=[], total_count=0))

        result = await search_memory.coroutine(
            config=_make_config(), query="q", folder="relationships"
        )

        assert result == "No matching memories found in 'relationships'."
        assert mock_engine.recall.await_args.kwargs["category_prefix"] == "relationships"
        assert _payloads(stream)[0] == {
            "action": "search",
            "query": "q",
            "folder": "relationships",
            "memories": [],
            "message": "No matching memories in 'relationships'",
        }

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
    async def test_engine_failure_propagates(self, mock_engine: MagicMock, log: MagicMock) -> None:
        # Unlike add_memory, a failed recall must NOT be reported to the model
        # as a plain string — a swallowed failure reads as "you have no
        # memories about that", which is a wrong answer, not a degraded one.
        mock_engine.recall = AsyncMock(side_effect=RuntimeError("chroma down"))

        with pytest.raises(RuntimeError, match="chroma down"):
            await search_memory.coroutine(config=_make_config(), query="q")

        _assert_failure_logged(log, "recall", "RuntimeError", "chroma down")

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
        self, mock_engine: MagicMock, stream: MagicMock, log: MagicMock
    ) -> None:
        updated = MemoryEntry(id="mem-2", content="new", category_path="home", version=2)
        mock_engine.update_memory = AsyncMock(return_value=updated)

        result = await update_memory.coroutine(
            config=_make_config(), memory_id="mem-1", new_content="new"
        )

        assert result == "Memory corrected (now v2 under 'home'). New ID: mem-2"
        mock_engine.update_memory.assert_awaited_once_with(FAKE_USER_ID, "mem-1", "new")
        _assert_success_log(
            log,
            memory=MemoryContext(operation="update", success=True, memory_id="mem-2"),
        )
        assert _payloads(stream)[0] == {
            "action": "update",
            "memories": [_serialized_entry(updated)],
            "message": "Memory corrected (now v2 under 'home')",
        }

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
    async def test_unknown_id_returns_a_corrective_error_without_streaming(
        self, mock_engine: MagicMock, stream: MagicMock, log: MagicMock
    ) -> None:
        mock_engine.update_memory = AsyncMock(return_value=None)

        result = await update_memory.coroutine(
            config=_make_config(), memory_id="gone", new_content="new"
        )

        assert result == (
            "Error: memory gone not found or already superseded — "
            "search_memory for the current version and use its ID."
        )
        stream.assert_not_called()
        log.warning.assert_called_once_with(
            "memory_tool_memory_not_found", operation="update", memory_id="gone"
        )

    async def test_missing_user_id_returns_error(self) -> None:
        result = await update_memory.coroutine(
            config=_make_config_no_user(), memory_id="m", new_content="c"
        )
        assert "user_id not found in config" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_engine_failure_propagates(self, mock_engine: MagicMock, log: MagicMock) -> None:
        mock_engine.update_memory = AsyncMock(side_effect=RuntimeError("pg down"))

        with pytest.raises(RuntimeError, match="pg down"):
            await update_memory.coroutine(config=_make_config(), memory_id="m", new_content="c")

        _assert_failure_logged(log, "update", "RuntimeError", "pg down")


# ---------------------------------------------------------------------------
# Tests: forget_memory
# ---------------------------------------------------------------------------


class TestForgetMemory:
    @patch(f"{MODULE}.memory_engine")
    async def test_confirms_the_id_and_reason(
        self, mock_engine: MagicMock, stream: MagicMock, log: MagicMock
    ) -> None:
        mock_engine.forget_memory = AsyncMock(return_value=True)

        result = await forget_memory.coroutine(
            config=_make_config(), memory_id="mem-1", reason="user moved"
        )

        assert result == "Memory forgotten: mem-1 (user moved)"
        mock_engine.forget_memory.assert_awaited_once_with(FAKE_USER_ID, "mem-1", "user moved")
        _assert_success_log(
            log,
            memory=MemoryContext(operation="delete", success=True, memory_id="mem-1"),
        )

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
        self, mock_engine: MagicMock, stream: MagicMock, log: MagicMock
    ) -> None:
        mock_engine.forget_memory = AsyncMock(return_value=False)

        result = await forget_memory.coroutine(config=_make_config(), memory_id="gone", reason="r")

        assert result == "Error: memory gone not found."
        stream.assert_not_called()
        log.warning.assert_called_once_with(
            "memory_tool_memory_not_found", operation="delete", memory_id="gone"
        )

    async def test_missing_user_id_returns_error(self) -> None:
        result = await forget_memory.coroutine(
            config=_make_config_no_user(), memory_id="m", reason="r"
        )
        assert "user_id not found in config" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_engine_failure_propagates(self, mock_engine: MagicMock, log: MagicMock) -> None:
        mock_engine.forget_memory = AsyncMock(side_effect=RuntimeError("pg down"))

        with pytest.raises(RuntimeError, match="pg down"):
            await forget_memory.coroutine(config=_make_config(), memory_id="m", reason="r")

        _assert_failure_logged(log, "delete", "RuntimeError", "pg down")


# ---------------------------------------------------------------------------
# Tests: search_journal
# ---------------------------------------------------------------------------


class TestSearchJournal:
    @patch(f"{MODULE}.memory_engine")
    async def test_renders_entry_hits_with_their_time(
        self, mock_engine: MagicMock, stream: MagicMock, log: MagicMock
    ) -> None:
        mock_engine.recall_episodes = AsyncMock(
            return_value=[
                EpisodeHit(date=date_type(2026, 3, 12), text="shipped the API", time="09:30"),
                EpisodeHit(date=date_type(2026, 3, 12), text="reviewed PRs", time="18:00"),
            ]
        )

        result = await search_journal.coroutine(config=_make_config(), query="shipped")

        assert result == (
            "Found journal activity on 1 days:\n"
            "- 2026-03-12 09:30: shipped the API\n"
            "- 2026-03-12 18:00: reviewed PRs"
        )
        mock_engine.recall_episodes.assert_awaited_once_with(FAKE_USER_ID, "shipped")
        _assert_success_log(
            log,
            memory=MemoryContext(
                operation="recall_episodes", success=True, query="shipped", result_count=1
            ),
        )
        assert _payloads(stream)[0] == {
            "action": "journal",
            "query": "shipped",
            "episodes": [
                {
                    "date": "2026-03-12",
                    "entries": [
                        {"time": "09:30", "text": "shipped the API", "source": None},
                        {"time": "18:00", "text": "reviewed PRs", "source": None},
                    ],
                    "summary": None,
                }
            ],
            "message": "Found journal activity on 1 days",
        }

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
        self, mock_engine: MagicMock, stream: MagicMock, log: MagicMock
    ) -> None:
        mock_engine.recall_episodes = AsyncMock(return_value=[])

        result = await search_journal.coroutine(config=_make_config(), query="nothing")

        assert result == "No journal entries matching 'nothing'."
        assert _payloads(stream)[0] == {
            "action": "journal",
            "query": "nothing",
            "episodes": [],
            "message": "No journal matches",
        }
        _assert_success_log(
            log,
            memory=MemoryContext(
                operation="recall_episodes", success=True, query="nothing", result_count=0
            ),
        )

    async def test_missing_user_id_returns_error(self) -> None:
        result = await search_journal.coroutine(config=_make_config_no_user(), query="q")
        assert "user_id not found in config" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_engine_failure_propagates(self, mock_engine: MagicMock, log: MagicMock) -> None:
        mock_engine.recall_episodes = AsyncMock(side_effect=RuntimeError("pg down"))

        with pytest.raises(RuntimeError, match="pg down"):
            await search_journal.coroutine(config=_make_config(), query="q")

        _assert_failure_logged(log, "recall_episodes", "RuntimeError", "pg down")


# ---------------------------------------------------------------------------
# Tests: search_conversations
# ---------------------------------------------------------------------------


class TestSearchConversations:
    @patch(f"{MODULE}.memory_engine")
    async def test_renders_each_passage_with_date_and_score(
        self, mock_engine: MagicMock, log: MagicMock
    ) -> None:
        mock_engine.recall_transcripts = AsyncMock(
            return_value=[
                ("2026-03-12", "the exact passage", 0.9123),
                ("2025-01-01", "the other passage", 0.5),
            ]
        )

        result = await search_conversations.coroutine(config=_make_config(), query="passage")

        assert result == (
            "Matching conversation passages:\n\n"
            "[2026-03-12] (match 0.91)\nthe exact passage\n\n"
            "[2025-01-01] (match 0.50)\nthe other passage"
        )
        mock_engine.recall_transcripts.assert_awaited_once_with(FAKE_USER_ID, "passage")
        _assert_success_log(
            log,
            memory=MemoryContext(
                operation="recall_transcripts", success=True, query="passage", result_count=2
            ),
        )

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
    async def test_engine_failure_propagates(self, mock_engine: MagicMock, log: MagicMock) -> None:
        mock_engine.recall_transcripts = AsyncMock(side_effect=RuntimeError("chroma down"))

        with pytest.raises(RuntimeError, match="chroma down"):
            await search_conversations.coroutine(config=_make_config(), query="q")

        _assert_failure_logged(log, "recall_transcripts", "RuntimeError", "chroma down")


# ---------------------------------------------------------------------------
# Tests: get_journal
# ---------------------------------------------------------------------------


class TestGetJournal:
    @staticmethod
    def _response(episode: MemoryEpisode | None) -> MemoryEpisodesResponse:
        return MemoryEpisodesResponse(episodes=[episode] if episode else [])

    @patch(f"{MODULE}.memory_engine")
    async def test_renders_summary_and_entries_for_the_day(
        self, mock_engine: MagicMock, stream: MagicMock, log: MagicMock
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

        assert result == (
            "Journal for 2026-03-12 (2 entries):\n"
            "Summary: a productive day\n"
            "- 09:30 shipped\n"
            "- 18:00 gym"
        )
        mock_engine.get_episodes.assert_awaited_once_with(
            FAKE_USER_ID, date_type(2026, 3, 12), date_type(2026, 3, 12)
        )
        _assert_success_log(
            log,
            memory=MemoryContext(
                operation="episodes",
                success=True,
                result_count=2,
                start="2026-03-12",
                end="2026-03-12",
            ),
        )
        assert _payloads(stream)[0] == {
            "action": "journal",
            "query": None,
            "episodes": [
                {
                    "date": "2026-03-12",
                    "entries": [
                        {"time": "09:30", "text": "shipped", "source": "conversation"},
                        {"time": "18:00", "text": "gym", "source": "conversation"},
                    ],
                    "summary": "a productive day",
                }
            ],
            "message": "Journal for 2026-03-12 (2 entries)",
        }

    @patch(f"{MODULE}.memory_engine")
    async def test_summary_only_day_is_rendered_without_entry_lines(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        episode = MemoryEpisode(date="2026-03-12", entries=[], summary="a quiet day")
        mock_engine.get_episodes = AsyncMock(return_value=self._response(episode))

        result = await get_journal.coroutine(config=_make_config(), date="2026-03-12")

        assert result == "Journal for 2026-03-12 (0 entries):\nSummary: a quiet day"

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

        assert result == "Journal for 2026-03-12 (1 entries):\n- 09:30 shipped"

    @patch(f"{MODULE}.memory_engine")
    async def test_trailing_whitespace_in_entry_text_is_stripped(
        self, mock_engine: MagicMock
    ) -> None:
        # .rstrip() (not .lstrip()): the line keeps its leading "- " while
        # trailing padding from a padded text field is trimmed.
        episode = MemoryEpisode(
            date="2026-03-12",
            entries=[MemoryEpisodeEntry(time="09:30", text="shipped   ", source="conversation")],
            summary=None,
        )
        mock_engine.get_episodes = AsyncMock(return_value=self._response(episode))

        result = await get_journal.coroutine(config=_make_config(), date="2026-03-12")

        assert result == "Journal for 2026-03-12 (1 entries):\n- 09:30 shipped"
        assert "shipped   " not in result

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
        self, mock_engine: MagicMock, stream: MagicMock, log: MagicMock
    ) -> None:
        mock_engine.get_episodes = AsyncMock(return_value=self._response(None))

        result = await get_journal.coroutine(config=_make_config(), date="2026-03-12")

        assert result == "No journal entries for 2026-03-12."
        assert _payloads(stream)[0] == {
            "action": "journal",
            "query": None,
            "episodes": [],
            "message": "No journal entries for 2026-03-12",
        }
        _assert_success_log(
            log,
            memory=MemoryContext(
                operation="episodes",
                success=True,
                result_count=0,
                start="2026-03-12",
                end="2026-03-12",
            ),
        )

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
        self, mock_engine: MagicMock, bad_date: str, log: MagicMock
    ) -> None:
        mock_engine.get_episodes = AsyncMock()

        result = await get_journal.coroutine(config=_make_config(), date=bad_date)

        assert f"Error: invalid date '{bad_date}'" in result
        assert "YYYY-MM-DD" in result
        mock_engine.get_episodes.assert_not_awaited()
        log.warning.assert_called_once_with(
            "memory_tool_invalid_date", operation="episodes", start=bad_date
        )

    async def test_missing_user_id_returns_error(self) -> None:
        result = await get_journal.coroutine(config=_make_config_no_user(), date="2026-03-12")
        assert "user_id not found in config" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_engine_failure_propagates(self, mock_engine: MagicMock, log: MagicMock) -> None:
        mock_engine.get_episodes = AsyncMock(side_effect=RuntimeError("pg down"))

        with pytest.raises(RuntimeError, match="pg down"):
            await get_journal.coroutine(config=_make_config(), date="2026-03-12")

        _assert_failure_logged(log, "episodes", "RuntimeError", "pg down")


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
        self, mock_engine: MagicMock, stream: MagicMock, log: MagicMock
    ) -> None:
        mock_engine.get_document = AsyncMock(return_value=_make_document())

        await read_memory_document.coroutine(config=_make_config(), doc_type="user")

        assert _payloads(stream)[0] == {
            "action": "document",
            "document": {
                "doc_type": "user_md",
                "content": "# About the user\nLikes coffee.",
                "version": 3,
                "updated_at": "2026-03-12T09:30:00+00:00",
            },
            "updated": False,
            "message": "Read the 'user' memory document (v3)",
        }
        _assert_success_log(
            log,
            memory=MemoryContext(operation="read_document", success=True, doc_type="user_md"),
        )

    @patch(f"{MODULE}.memory_engine")
    async def test_missing_document_explains_it_fills_in_automatically(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.get_document = AsyncMock(return_value=None)

        result = await read_memory_document.coroutine(config=_make_config(), doc_type="agenda")

        assert result == (
            "The 'agenda' document is empty — nothing has been written to it yet. "
            "It fills in automatically as memory accumulates."
        )
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
    async def test_unknown_doc_type_lists_the_valid_choices(
        self, mock_engine: MagicMock, log: MagicMock
    ) -> None:
        mock_engine.get_document = AsyncMock()

        result = await read_memory_document.coroutine(config=_make_config(), doc_type="diary")

        assert "unknown document 'diary'" in result
        for filename in MEMORY_DOC_FILENAMES.values():
            assert filename.removesuffix(".md") in result
        mock_engine.get_document.assert_not_awaited()
        log.warning.assert_called_once_with(
            "memory_tool_unknown_doc", operation="read_document", doc_type="diary"
        )

    async def test_missing_user_id_returns_error(self) -> None:
        result = await read_memory_document.coroutine(
            config=_make_config_no_user(), doc_type="user"
        )
        assert "user_id not found in config" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_engine_failure_propagates(self, mock_engine: MagicMock, log: MagicMock) -> None:
        mock_engine.get_document = AsyncMock(side_effect=RuntimeError("pg down"))

        with pytest.raises(RuntimeError, match="pg down"):
            await read_memory_document.coroutine(config=_make_config(), doc_type="user")

        _assert_failure_logged(log, "read_document", "RuntimeError", "pg down")


# ---------------------------------------------------------------------------
# Tests: update_memory_document
# ---------------------------------------------------------------------------


class TestUpdateMemoryDocument:
    @patch(f"{MODULE}.memory_engine")
    async def test_reports_the_new_version_and_the_replace_semantics(
        self, mock_engine: MagicMock, stream: MagicMock, log: MagicMock
    ) -> None:
        mock_engine.update_document = AsyncMock(return_value=_make_document(version=4))

        result = await update_memory_document.coroutine(
            config=_make_config(), doc_type="user", content="# New"
        )

        assert result == (
            "Rewrote the 'user' memory document (now v4). "
            "The full content was replaced; prior versions are kept as history."
        )
        mock_engine.update_document.assert_awaited_once_with(
            FAKE_USER_ID, MemoryDocType.USER_MD, "# New"
        )
        _assert_success_log(
            log,
            memory=MemoryContext(
                operation="update_document", success=True, doc_type="user_md"
            ),
        )
        assert _payloads(stream)[0] == {
            "action": "document",
            "document": {
                "doc_type": "user_md",
                "content": "# About the user\nLikes coffee.",
                "version": 4,
                "updated_at": "2026-03-12T09:30:00+00:00",
            },
            "updated": True,
            "message": "Rewrote the 'user' memory document (now v4)",
        }

    @patch(f"{MODULE}.memory_engine")
    async def test_streams_the_document_payload_marked_updated(
        self, mock_engine: MagicMock, stream: MagicMock
    ) -> None:
        mock_engine.update_document = AsyncMock(
            return_value=_make_document(doc_type=MemoryDocType.INSIGHTS_MD, version=2)
        )

        await update_memory_document.coroutine(
            config=_make_config(), doc_type="insights", content="# New"
        )

        payload = _payloads(stream)[0]
        assert payload["action"] == "document"
        assert payload["updated"] is True
        assert payload["document"]["doc_type"] == "insights_md"
        assert payload["document"]["version"] == 2
        assert payload["message"] == "Rewrote the 'insights' memory document (now v2)"

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
        self, mock_engine: MagicMock, log: MagicMock
    ) -> None:
        mock_engine.update_document = AsyncMock()

        result = await update_memory_document.coroutine(
            config=_make_config(), doc_type="scratchpad", content="# New"
        )

        assert "unknown document 'scratchpad'" in result
        mock_engine.update_document.assert_not_awaited()
        log.warning.assert_called_once_with(
            "memory_tool_unknown_doc", operation="update_document", doc_type="scratchpad"
        )

    async def test_missing_user_id_returns_error(self) -> None:
        result = await update_memory_document.coroutine(
            config=_make_config_no_user(), doc_type="user", content="c"
        )
        assert "user_id not found in config" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_engine_failure_propagates(self, mock_engine: MagicMock, log: MagicMock) -> None:
        mock_engine.update_document = AsyncMock(side_effect=RuntimeError("pg down"))

        with pytest.raises(RuntimeError, match="pg down"):
            await update_memory_document.coroutine(
                config=_make_config(), doc_type="user", content="c"
            )

        _assert_failure_logged(log, "update_document", "RuntimeError", "pg down")
