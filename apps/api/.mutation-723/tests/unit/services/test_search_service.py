"""Unit tests for the search service.

``search_messages`` orchestrates two repositories (conversations + notes) and
assembles the response with highlight snippets. These tests mock the repository
singletons (services never mock the DB) and assert the service's own behaviour:
response shape, snippet attachment, error mapping, and — critically — that the
user query is regex-escaped before it reaches either repository.
"""

import re
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import pytest

from app.models.conversation_models import (
    ConversationDescriptionHit,
    ConversationMessageHit,
    ConversationSearchResults,
)
from app.models.notes_models import NoteSearchHit
from app.services import search_service
from app.services.search_service import search_messages

FAKE_USER_ID = "507f1f77bcf86cd799439011"


@pytest.fixture
def mock_conversation_repo():
    repo = AsyncMock()
    with patch.object(search_service, "conversation_repository", repo):
        yield repo


@pytest.fixture
def mock_note_repo():
    repo = AsyncMock()
    with patch.object(search_service, "note_repository", repo):
        yield repo


@pytest.fixture
def mock_get_context_window():
    with patch.object(
        search_service, "get_context_window", return_value="...matched text..."
    ) as mock_fn:
        yield mock_fn


def _conversation_results() -> ConversationSearchResults:
    return ConversationSearchResults(
        messages=[
            ConversationMessageHit(
                conversation_id="conv1",
                message={
                    "type": "bot",
                    "response": "test response about Python",
                    "message_id": "m1",
                },
            ),
            ConversationMessageHit(
                conversation_id="conv2",
                message={"type": "bot", "response": "Python programming", "message_id": "m2"},
            ),
        ],
        conversations=[
            ConversationDescriptionHit(conversation_id="conv3", description="A Python tutorial")
        ],
    )


def _note_hits() -> list[NoteSearchHit]:
    return [
        NoteSearchHit(id="n1", note_id="note1", plaintext="Python is great for data science"),
        NoteSearchHit(id="n2", note_id="note2", plaintext="Learning Python basics"),
    ]


class TestSearchMessagesHappyPath:
    async def test_returns_all_three_sources_with_snippets(
        self, mock_conversation_repo, mock_note_repo, mock_get_context_window
    ):
        mock_conversation_repo.search.return_value = _conversation_results()
        mock_note_repo.search_by_plaintext.return_value = _note_hits()

        result = await search_messages("Python", FAKE_USER_ID)

        assert len(result.messages) == 2
        assert len(result.conversations) == 1
        assert len(result.notes) == 2
        assert all(m.snippet == "...matched text..." for m in result.messages)
        assert all(n.snippet == "...matched text..." for n in result.notes)
        assert result.messages[0].conversation_id == "conv1"
        assert result.notes[0].id == "n1"


class TestSearchMessagesEmpty:
    async def test_returns_empty_when_no_results(
        self, mock_conversation_repo, mock_note_repo, mock_get_context_window
    ):
        mock_conversation_repo.search.return_value = ConversationSearchResults()
        mock_note_repo.search_by_plaintext.return_value = []

        result = await search_messages("nonexistent", FAKE_USER_ID)

        assert result.messages == []
        assert result.conversations == []
        assert result.notes == []


class TestSearchMessagesErrors:
    async def test_raises_500_on_repository_error(
        self, mock_conversation_repo, mock_note_repo, mock_get_context_window
    ):
        mock_conversation_repo.search.side_effect = Exception("DB connection failed")

        with pytest.raises(HTTPException) as exc_info:
            await search_messages("Python", FAKE_USER_ID)

        assert exc_info.value.status_code == 500
        assert "Failed to perform search" in exc_info.value.detail

    async def test_error_detail_contains_exception_message(
        self, mock_conversation_repo, mock_note_repo, mock_get_context_window
    ):
        mock_conversation_repo.search.side_effect = Exception("timeout reached")

        with pytest.raises(HTTPException) as exc_info:
            await search_messages("query", FAKE_USER_ID)

        assert "timeout reached" in exc_info.value.detail


class TestSearchMessagesRegexEscaping:
    async def test_query_is_regex_escaped_before_reaching_repositories(
        self, mock_conversation_repo, mock_note_repo, mock_get_context_window
    ):
        """A metacharacter-laden query must reach both repositories as an escaped
        literal — never the raw pattern (ReDoS / regex-injection hardening)."""
        mock_conversation_repo.search.return_value = ConversationSearchResults()
        mock_note_repo.search_by_plaintext.return_value = []

        raw_query = "a.*(b|c)+[x]$"
        escaped = re.escape(raw_query)
        assert escaped != raw_query  # meaningful only if it has metacharacters

        await search_messages(raw_query, FAKE_USER_ID)

        assert mock_conversation_repo.search.call_args.kwargs["pattern"] == escaped
        assert mock_note_repo.search_by_plaintext.call_args.kwargs["pattern"] == escaped
        # And each repository is scoped to the caller.
        assert mock_conversation_repo.search.call_args[0][0] == FAKE_USER_ID
        assert mock_note_repo.search_by_plaintext.call_args[0][0] == FAKE_USER_ID
