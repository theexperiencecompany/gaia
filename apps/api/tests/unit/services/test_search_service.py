"""Unit tests for search service operations."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.services.search_service import search_messages


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"


@pytest.fixture
def mock_conversations_collection():
    with patch("app.services.search_service.conversations_collection") as mock_col:
        yield mock_col


@pytest.fixture
def mock_notes_collection():
    with patch("app.services.search_service.notes_collection") as mock_col:
        yield mock_col


@pytest.fixture
def mock_convert_legacy():
    with patch(
        "app.services.search_service.convert_legacy_tool_data",
        side_effect=lambda m: m,
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_get_context_window():
    with patch(
        "app.services.search_service.get_context_window",
        return_value="...matched text...",
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def sample_conversation_results():
    return [
        {
            "messages": [
                {
                    "conversation_id": "conv1",
                    "message": {
                        "response": "Hello, this is a test response about Python.",
                    },
                },
                {
                    "conversation_id": "conv2",
                    "message": {
                        "response": "Another result mentioning Python programming.",
                    },
                },
            ],
            "conversations": [
                {
                    "conversation_id": "conv3",
                    "description": "A Python tutorial session",
                },
            ],
        }
    ]


@pytest.fixture
def sample_notes_results():
    return [
        {
            "_id": MagicMock(),
            "note_id": "note1",
            "plaintext": "Python is a great language for data science.",
        },
        {
            "_id": MagicMock(),
            "note_id": "note2",
            "plaintext": "Learning Python basics and advanced topics.",
        },
    ]


# ---------------------------------------------------------------------------
# search_messages — happy paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchMessagesHappyPath:
    async def test_returns_messages_conversations_and_notes(
        self,
        mock_conversations_collection,
        mock_notes_collection,
        mock_convert_legacy,
        mock_get_context_window,
        sample_conversation_results,
        sample_notes_results,
    ):
        # Setup conversation aggregation
        conv_cursor = MagicMock()
        conv_cursor.to_list = AsyncMock(return_value=sample_conversation_results)
        mock_conversations_collection.aggregate.return_value = conv_cursor

        # Setup notes aggregation
        notes_cursor = MagicMock()
        notes_cursor.to_list = AsyncMock(return_value=sample_notes_results)
        mock_notes_collection.aggregate.return_value = notes_cursor

        result = await search_messages("Python", FAKE_USER_ID)

        assert "messages" in result
        assert "conversations" in result
        assert "notes" in result
        assert len(result["messages"]) == 2
        assert len(result["conversations"]) == 1
        assert len(result["notes"]) == 2

    async def test_messages_have_snippets(
        self,
        mock_conversations_collection,
        mock_notes_collection,
        mock_convert_legacy,
        mock_get_context_window,
        sample_conversation_results,
    ):
        conv_cursor = MagicMock()
        conv_cursor.to_list = AsyncMock(return_value=sample_conversation_results)
        mock_conversations_collection.aggregate.return_value = conv_cursor

        notes_cursor = MagicMock()
        notes_cursor.to_list = AsyncMock(return_value=[])
        mock_notes_collection.aggregate.return_value = notes_cursor

        result = await search_messages("Python", FAKE_USER_ID)

        for msg in result["messages"]:
            assert "snippet" in msg

    async def test_notes_have_snippets(
        self,
        mock_conversations_collection,
        mock_notes_collection,
        mock_convert_legacy,
        mock_get_context_window,
        sample_notes_results,
    ):
        conv_cursor = MagicMock()
        conv_cursor.to_list = AsyncMock(
            return_value=[{"messages": [], "conversations": []}]
        )
        mock_conversations_collection.aggregate.return_value = conv_cursor

        notes_cursor = MagicMock()
        notes_cursor.to_list = AsyncMock(return_value=sample_notes_results)
        mock_notes_collection.aggregate.return_value = notes_cursor

        result = await search_messages("Python", FAKE_USER_ID)

        for note in result["notes"]:
            assert "snippet" in note

    async def test_legacy_tool_data_conversion(
        self,
        mock_conversations_collection,
        mock_notes_collection,
        mock_convert_legacy,
        mock_get_context_window,
        sample_conversation_results,
    ):
        conv_cursor = MagicMock()
        conv_cursor.to_list = AsyncMock(return_value=sample_conversation_results)
        mock_conversations_collection.aggregate.return_value = conv_cursor

        notes_cursor = MagicMock()
        notes_cursor.to_list = AsyncMock(return_value=[])
        mock_notes_collection.aggregate.return_value = notes_cursor

        await search_messages("Python", FAKE_USER_ID)

        # convert_legacy_tool_data should be called for each message
        assert mock_convert_legacy.call_count == 2


# ---------------------------------------------------------------------------
# search_messages — empty results
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchMessagesEmpty:
    async def test_returns_empty_when_no_results(
        self,
        mock_conversations_collection,
        mock_notes_collection,
        mock_convert_legacy,
        mock_get_context_window,
    ):
        conv_cursor = MagicMock()
        conv_cursor.to_list = AsyncMock(
            return_value=[{"messages": [], "conversations": []}]
        )
        mock_conversations_collection.aggregate.return_value = conv_cursor

        notes_cursor = MagicMock()
        notes_cursor.to_list = AsyncMock(return_value=[])
        mock_notes_collection.aggregate.return_value = notes_cursor

        result = await search_messages("nonexistent", FAKE_USER_ID)

        assert result["messages"] == []
        assert result["conversations"] == []
        assert result["notes"] == []

    async def test_handles_empty_aggregate_result(
        self,
        mock_conversations_collection,
        mock_notes_collection,
        mock_convert_legacy,
        mock_get_context_window,
    ):
        """When aggregate returns an empty list (no facet results)."""
        conv_cursor = MagicMock()
        conv_cursor.to_list = AsyncMock(return_value=[])
        mock_conversations_collection.aggregate.return_value = conv_cursor

        notes_cursor = MagicMock()
        notes_cursor.to_list = AsyncMock(return_value=[])
        mock_notes_collection.aggregate.return_value = notes_cursor

        result = await search_messages("test", FAKE_USER_ID)

        assert result["messages"] == []
        assert result["conversations"] == []


# ---------------------------------------------------------------------------
# search_messages — error handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchMessagesErrors:
    async def test_raises_500_on_db_error(
        self,
        mock_conversations_collection,
        mock_notes_collection,
        mock_convert_legacy,
        mock_get_context_window,
    ):
        conv_cursor = MagicMock()
        conv_cursor.to_list = AsyncMock(side_effect=Exception("DB connection failed"))
        mock_conversations_collection.aggregate.return_value = conv_cursor

        with pytest.raises(HTTPException) as exc_info:
            await search_messages("Python", FAKE_USER_ID)

        assert exc_info.value.status_code == 500
        assert "Failed to perform search" in exc_info.value.detail

    async def test_raises_500_on_notes_db_error(
        self,
        mock_conversations_collection,
        mock_notes_collection,
        mock_convert_legacy,
        mock_get_context_window,
    ):
        conv_cursor = MagicMock()
        conv_cursor.to_list = AsyncMock(
            return_value=[{"messages": [], "conversations": []}]
        )
        mock_conversations_collection.aggregate.return_value = conv_cursor

        notes_cursor = MagicMock()
        notes_cursor.to_list = AsyncMock(
            side_effect=Exception("Notes collection error")
        )
        mock_notes_collection.aggregate.return_value = notes_cursor

        with pytest.raises(HTTPException) as exc_info:
            await search_messages("test", FAKE_USER_ID)

        assert exc_info.value.status_code == 500

    async def test_error_detail_contains_exception_message(
        self,
        mock_conversations_collection,
        mock_notes_collection,
        mock_convert_legacy,
        mock_get_context_window,
    ):
        conv_cursor = MagicMock()
        conv_cursor.to_list = AsyncMock(side_effect=Exception("timeout reached"))
        mock_conversations_collection.aggregate.return_value = conv_cursor

        with pytest.raises(HTTPException) as exc_info:
            await search_messages("query", FAKE_USER_ID)

        assert "timeout reached" in exc_info.value.detail


# ---------------------------------------------------------------------------
# search_messages — edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchMessagesEdgeCases:
    async def test_single_character_query(
        self,
        mock_conversations_collection,
        mock_notes_collection,
        mock_convert_legacy,
        mock_get_context_window,
    ):
        conv_cursor = MagicMock()
        conv_cursor.to_list = AsyncMock(
            return_value=[{"messages": [], "conversations": []}]
        )
        mock_conversations_collection.aggregate.return_value = conv_cursor

        notes_cursor = MagicMock()
        notes_cursor.to_list = AsyncMock(return_value=[])
        mock_notes_collection.aggregate.return_value = notes_cursor

        result = await search_messages("a", FAKE_USER_ID)

        assert isinstance(result, dict)
        # Verify the query was used in the aggregation pipeline
        pipeline = mock_conversations_collection.aggregate.call_args[0][0]
        match_stage = pipeline[0]
        assert match_stage["$match"]["user_id"] == FAKE_USER_ID

    async def test_special_characters_in_query(
        self,
        mock_conversations_collection,
        mock_notes_collection,
        mock_convert_legacy,
        mock_get_context_window,
    ):
        """Ensure special characters in query don't crash the service."""
        conv_cursor = MagicMock()
        conv_cursor.to_list = AsyncMock(
            return_value=[{"messages": [], "conversations": []}]
        )
        mock_conversations_collection.aggregate.return_value = conv_cursor

        notes_cursor = MagicMock()
        notes_cursor.to_list = AsyncMock(return_value=[])
        mock_notes_collection.aggregate.return_value = notes_cursor

        # Should not raise
        result = await search_messages("test (query) [with] $pecial", FAKE_USER_ID)

        assert isinstance(result, dict)

    async def test_notes_serialized_with_id_field(
        self,
        mock_conversations_collection,
        mock_notes_collection,
        mock_convert_legacy,
        mock_get_context_window,
    ):
        """Notes should be serialized using serialize_document, converting _id to id."""
        from bson import ObjectId

        oid = ObjectId()
        notes = [
            {
                "_id": oid,
                "note_id": "note_x",
                "plaintext": "serialization test",
            }
        ]

        conv_cursor = MagicMock()
        conv_cursor.to_list = AsyncMock(
            return_value=[{"messages": [], "conversations": []}]
        )
        mock_conversations_collection.aggregate.return_value = conv_cursor

        notes_cursor = MagicMock()
        notes_cursor.to_list = AsyncMock(return_value=notes)
        mock_notes_collection.aggregate.return_value = notes_cursor

        result = await search_messages("serialization", FAKE_USER_ID)

        assert len(result["notes"]) == 1
        note = result["notes"][0]
        assert "id" in note
        assert note["id"] == str(oid)
        assert "snippet" in note

    async def test_messages_without_message_key_skipped(
        self,
        mock_conversations_collection,
        mock_notes_collection,
        mock_convert_legacy,
        mock_get_context_window,
    ):
        """Messages without 'message' key are skipped by the if-guard."""
        results = [
            {
                "messages": [
                    {
                        "conversation_id": "conv1",
                        "message": {"response": "Has message key"},
                    },
                    {
                        "conversation_id": "conv2",
                    },
                ],
                "conversations": [],
            }
        ]

        conv_cursor = MagicMock()
        conv_cursor.to_list = AsyncMock(return_value=results)
        mock_conversations_collection.aggregate.return_value = conv_cursor

        notes_cursor = MagicMock()
        notes_cursor.to_list = AsyncMock(return_value=[])
        mock_notes_collection.aggregate.return_value = notes_cursor

        await search_messages("test", FAKE_USER_ID)

        # Only one message has "message" key, so convert_legacy is called once
        assert mock_convert_legacy.call_count == 1
