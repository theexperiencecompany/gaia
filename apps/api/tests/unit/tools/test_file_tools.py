"""Behavior tests for app.agents.tools.file_tools.

Locks: conversation-scoped semantic search (file_id filter intersection with
the conversation's own files, k=5), the no-client / no-files / out-of-scope
short-circuits, and the content construction from the different
``page_wise_summary`` shapes (str / list / dict / None).
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.documents import Document
import pytest

from app.agents.tools.file_tools import _construct_content, search_uploaded_files
from app.models.files_models import FileDocument

MODULE = "app.agents.tools.file_tools"


def _config() -> dict[str, Any]:
    """The configurable as the executor actually sees it.

    The tool is bound to the executor, which runs on the derived
    ``executor_<conversation_id>`` thread — so ``thread_id`` names a conversation
    that owns no files, and the two ids are deliberately different here. A
    lookup that reads ``thread_id`` must not find "conv-1".
    """
    return {
        "configurable": {
            "thread_id": "executor_conv-1",
            "conversation_id": "conv-1",
            "user_id": "user-1",
        }
    }


def _file(file_id: str, summary: Any = None, description: str | None = None) -> FileDocument:
    return FileDocument(
        user_id="user-1",
        file_id=file_id,
        filename="a.pdf",
        type="pdf",
        size=10,
        url="https://x/a.pdf",
        description=description,
        page_wise_summary=summary,
        created_at=datetime.now(UTC),
    )


def _patch_collection(return_value: list[tuple[Document, float]]) -> tuple[MagicMock, AsyncMock]:
    collection = MagicMock()
    collection.asimilarity_search_with_score = AsyncMock(return_value=return_value)
    return collection, AsyncMock(return_value=collection)


class TestGetSimilarDocuments:
    async def test_filters_by_user_and_conversation_files(self) -> None:
        collection, get_client = _patch_collection(
            [(Document(page_content="x", metadata={"file_id": "f1"}), 0.9)]
        )
        with (
            patch(f"{MODULE}.ChromaClient.get_langchain_client", get_client),
            patch(
                f"{MODULE}.file_repository.find_ids_for_conversation",
                AsyncMock(return_value=["f1", "f2"]),
            ),
        ):
            from app.agents.tools.file_tools import _get_similar_documents

            result = await _get_similar_documents("query", "conv-1", "user-1")

        assert result == [(Document(page_content="x", metadata={"file_id": "f1"}), 0.9)]
        search_call = collection.asimilarity_search_with_score.await_args
        assert search_call.kwargs["query"] == "query"
        assert search_call.kwargs["k"] == 5
        assert search_call.kwargs["filter"] == {
            "$and": [{"user_id": "user-1"}, {"file_id": {"$in": ["f1", "f2"]}}]
        }

    async def test_restricted_file_id_filters_further(self) -> None:
        collection, get_client = _patch_collection([])
        with (
            patch(f"{MODULE}.ChromaClient.get_langchain_client", get_client),
            patch(
                f"{MODULE}.file_repository.find_ids_for_conversation",
                AsyncMock(return_value=["f1", "f2"]),
            ),
        ):
            from app.agents.tools.file_tools import _get_similar_documents

            await _get_similar_documents("query", "conv-1", "user-1", file_id="f2")

        filters = collection.asimilarity_search_with_score.await_args.kwargs["filter"]
        assert filters["$and"][1] == {"file_id": {"$in": ["f2"]}}

    async def test_no_chroma_client_returns_empty(self) -> None:
        with (
            patch(f"{MODULE}.ChromaClient.get_langchain_client", AsyncMock(return_value=None)),
            patch(
                f"{MODULE}.file_repository.find_ids_for_conversation",
                AsyncMock(return_value=["f1"]),
            ) as find,
        ):
            from app.agents.tools.file_tools import _get_similar_documents

            assert await _get_similar_documents("query", "conv-1", "user-1") == []
        find.assert_not_called()

    async def test_no_conversation_files_returns_empty(self) -> None:
        collection, get_client = _patch_collection([])
        with (
            patch(f"{MODULE}.ChromaClient.get_langchain_client", get_client),
            patch(
                f"{MODULE}.file_repository.find_ids_for_conversation",
                AsyncMock(return_value=[]),
            ),
        ):
            from app.agents.tools.file_tools import _get_similar_documents

            assert await _get_similar_documents("query", "conv-1", "user-1") == []
        collection.asimilarity_search_with_score.assert_not_called()

    async def test_file_id_outside_the_conversation_raises_with_the_valid_ids(self) -> None:
        """An unknown id must fail loud, not read as "the file says nothing".

        The agent is never shown a file's id, so a guessed filename lands here
        every time; the error has to name the ids it could have used instead.
        """
        collection, get_client = _patch_collection([])
        with (
            patch(f"{MODULE}.ChromaClient.get_langchain_client", get_client),
            patch(
                f"{MODULE}.file_repository.find_ids_for_conversation",
                AsyncMock(return_value=["f1"]),
            ),
        ):
            from app.agents.tools.file_tools import _get_similar_documents

            with pytest.raises(ValueError, match=r"No uploaded file with id 'other'.*\['f1'\]"):
                await _get_similar_documents("query", "conv-1", "user-1", file_id="other")
        collection.asimilarity_search_with_score.assert_not_called()


class TestConstructContent:
    def test_string_summary_is_used_directly(self) -> None:
        docs = [_file("f1", summary="a whole-file summary")]
        similar = [(Document(page_content="x", metadata={"file_id": "f1"}), 0.8)]

        content = _construct_content(docs, similar)

        assert content == "Document ID: f1\nDescription: a whole-file summary\n\n"

    def test_list_summary_selects_the_matching_page(self) -> None:
        docs = [
            _file(
                "f1",
                summary=[
                    {"data": {"page_number": 1, "content": "page one"}},
                    {"data": {"page_number": 2, "content": "page two"}},
                ],
            )
        ]
        similar = [(Document(page_content="x", metadata={"file_id": "f1", "page_number": 2}), 0.8)]

        content = _construct_content(docs, similar)

        assert "Page Number: 2" in content
        assert "page two" in content
        assert "page one" not in content

    def test_dict_summary_reads_its_content(self) -> None:
        docs = [_file("f1", summary={"data": {"content": "dict content"}})]
        similar = [(Document(page_content="x", metadata={"file_id": "f1"}), 0.8)]

        content = _construct_content(docs, similar)

        assert content == "Document ID: f1\nDescription: dict content\n\n"

    def test_missing_summary_falls_back_to_description(self) -> None:
        docs = [_file("f1", summary=None, description="a short description")]
        similar = [(Document(page_content="x", metadata={"file_id": "f1"}), 0.8)]

        content = _construct_content(docs, similar)

        assert content == "Document ID: f1\nDescription: a short description\n\n"

    def test_similar_document_without_a_matching_file_is_skipped(self) -> None:
        docs: list[FileDocument] = []
        similar = [(Document(page_content="x", metadata={"file_id": "ghost"}), 0.8)]

        assert _construct_content(docs, similar) == ""


class TestSearchUploadedFiles:
    async def test_happy_path_returns_constructed_content(self) -> None:
        docs = [_file("f1", summary="whole-file summary")]
        similar = [(Document(page_content="x", metadata={"file_id": "f1"}), 0.8)]
        with (
            patch(
                f"{MODULE}._get_similar_documents", AsyncMock(return_value=similar)
            ) as get_similar,
            patch(
                f"{MODULE}.file_repository.find_by_ids_for_user", AsyncMock(return_value=docs)
            ) as find,
        ):
            result = await search_uploaded_files.coroutine(
                query="quarterly results", file_id=None, config=_config()
            )

        assert "Document ID: f1" in result
        get_similar.assert_awaited_once_with(
            query="quarterly results", conversation_id="conv-1", file_id=None, user_id="user-1"
        )
        find.assert_awaited_once_with(["f1"], "user-1")

    async def test_file_id_is_forwarded_into_the_search(self) -> None:
        with (
            patch(f"{MODULE}._get_similar_documents", AsyncMock(return_value=[])) as get_similar,
            patch(f"{MODULE}.file_repository.find_by_ids_for_user", AsyncMock(return_value=[])),
        ):
            await search_uploaded_files.coroutine(query="q", file_id="f9", config=_config())

        get_similar.assert_awaited_once_with(
            query="q", conversation_id="conv-1", file_id="f9", user_id="user-1"
        )

    async def test_missing_configurable_raises(self) -> None:
        with (
            patch(f"{MODULE}._get_similar_documents", AsyncMock()),
            patch(f"{MODULE}.file_repository.find_by_ids_for_user", AsyncMock()),
        ):
            with pytest.raises(ValueError, match="Configurable is not set"):
                await search_uploaded_files.coroutine(
                    query="q", file_id=None, config={"not_configurable": True}
                )

    async def test_downstream_failure_propagates(self) -> None:
        with (
            patch(
                f"{MODULE}._get_similar_documents",
                AsyncMock(side_effect=RuntimeError("chroma down")),
            ),
            patch(f"{MODULE}.file_repository.find_by_ids_for_user", AsyncMock()),
        ):
            with pytest.raises(RuntimeError, match="chroma down"):
                await search_uploaded_files.coroutine(query="q", file_id=None, config=_config())
