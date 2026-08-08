"""Unit tests for gaia_knowledge_service (GAIA self-knowledge in ChromaDB)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError
import pytest

from app.services.gaia_knowledge_service import (
    KnowledgeItem,
    KnowledgeResult,
    gaia_knowledge_service,
)

_MOD = "app.services.gaia_knowledge_service"


@pytest.fixture
def mock_chroma():
    client = MagicMock()
    client.asimilarity_search_with_score = AsyncMock(return_value=[])
    client.aadd_texts = AsyncMock()
    client.delete_collection = AsyncMock()
    client.create_collection = AsyncMock()
    with patch(f"{_MOD}.ChromaClient") as m_cls:
        m_cls.get_langchain_client = AsyncMock(return_value=client)
        m_cls.get_client = AsyncMock(return_value=client)
        yield client


class TestKnowledgeItemValidation:
    def test_accepts_non_empty_content(self):
        item = KnowledgeItem(content="GAIA can send emails")

        assert item.content == "GAIA can send emails"

    def test_rejects_empty_content(self):
        with pytest.raises(ValidationError):
            KnowledgeItem(content="")

    def test_rejects_whitespace_only_content(self):
        with pytest.raises(ValidationError):
            KnowledgeItem(content="   \n\t  ")

    def test_strips_whitespace(self):
        item = KnowledgeItem(content="  padded  ")

        assert item.content == "padded"


class TestSearchKnowledge:
    async def test_returns_scored_results(self, mock_chroma):
        mock_chroma.asimilarity_search_with_score.return_value = [
            (
                SimpleNamespace(
                    page_content="GAIA supports Gmail", metadata={"kind": "capability"}
                ),
                0.95,
            ),
            (SimpleNamespace(page_content="GAIA has memory", metadata={}), 0.8),
        ]

        results = await gaia_knowledge_service.search_knowledge("can GAIA email me?", limit=2)

        assert results == [
            KnowledgeResult(
                content="GAIA supports Gmail", relevance_score=0.95, metadata={"kind": "capability"}
            ),
            KnowledgeResult(content="GAIA has memory", relevance_score=0.8, metadata={}),
        ]

    async def test_empty_results(self, mock_chroma):
        mock_chroma.asimilarity_search_with_score.return_value = []

        assert await gaia_knowledge_service.search_knowledge("anything") == []

    async def test_search_failure_degrades_to_empty(self, mock_chroma):
        mock_chroma.asimilarity_search_with_score.side_effect = RuntimeError("chroma down")

        assert await gaia_knowledge_service.search_knowledge("anything") == []


class TestAddKnowledgeBatch:
    async def test_empty_batch_returns_zero_without_touching_chroma(self, mock_chroma):
        assert await gaia_knowledge_service.add_knowledge_batch([]) == 0
        mock_chroma.aadd_texts.assert_not_awaited()

    async def test_adds_texts_and_metadatas(self, mock_chroma):
        items = [
            KnowledgeItem(content="A", metadata={"x": 1}),
            KnowledgeItem(content="B"),
        ]

        count = await gaia_knowledge_service.add_knowledge_batch(items)

        assert count == 2
        mock_chroma.aadd_texts.assert_awaited_once()
        assert mock_chroma.aadd_texts.await_args.kwargs["texts"] == ["A", "B"]
        assert mock_chroma.aadd_texts.await_args.kwargs["metadatas"] == [{"x": 1}, {}]

    async def test_failure_degrades_to_zero(self, mock_chroma):
        mock_chroma.aadd_texts.side_effect = RuntimeError("chroma down")

        assert await gaia_knowledge_service.add_knowledge_batch([KnowledgeItem(content="A")]) == 0


class TestClearKnowledge:
    async def test_deletes_and_recreates_collection(self, mock_chroma):
        ok = await gaia_knowledge_service.clear_knowledge()

        assert ok is True
        mock_chroma.delete_collection.assert_awaited_once_with(name="gaia_knowledge")
        mock_chroma.create_collection.assert_awaited_once()
        assert mock_chroma.create_collection.await_args.kwargs["name"] == "gaia_knowledge"
        assert mock_chroma.create_collection.await_args.kwargs["metadata"] == {
            "hnsw:space": "cosine"
        }

    async def test_failure_degrades_to_false(self, mock_chroma):
        mock_chroma.delete_collection.side_effect = RuntimeError("chroma down")

        assert await gaia_knowledge_service.clear_knowledge() is False
