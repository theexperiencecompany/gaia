"""Unit tests for file service operations."""

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.models.files_models import DocumentPageModel, DocumentSummaryModel
from app.models.message_models import FileData
from app.services.file_service import (
    _process_file_summary,
    _store_in_chromadb,
    _store_in_mongodb,
    delete_file_service,
    deserialize_file,
    fetch_files,
    get_files,
    update_file_in_chromadb,
    update_file_service,
    upload_file_service,
)

# The caching decorators import delete_cache/get_cache/set_cache from
# app.decorators.caching, so patches must target that module.
PATCH_DELETE_CACHE = "app.decorators.caching.delete_cache"
PATCH_GET_CACHE = "app.decorators.caching.get_cache"
PATCH_SET_CACHE = "app.decorators.caching.set_cache"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_files_collection():
    with patch("app.services.file_service.files_collection") as mock_col:
        yield mock_col


@pytest.fixture
def mock_cloudinary_upload():
    with patch("app.services.file_service.cloudinary.uploader.upload") as mock_upload:
        yield mock_upload


@pytest.fixture
def mock_cloudinary_destroy():
    with patch("app.services.file_service.cloudinary.uploader.destroy") as mock_destroy:
        yield mock_destroy


@pytest.fixture
def mock_chroma_client():
    with patch("app.services.file_service.ChromaClient") as mock_chroma:
        mock_collection = AsyncMock()
        mock_chroma.get_langchain_client = AsyncMock(return_value=mock_collection)
        yield mock_chroma, mock_collection


@pytest.fixture
def mock_search_documents():
    with patch(
        "app.services.file_service.search_documents_by_similarity",
        new_callable=AsyncMock,
    ) as mock_search:
        yield mock_search


@pytest.fixture
def sample_document_summary_model():
    return DocumentSummaryModel(
        data=DocumentPageModel(page_number=1, content="Page 1 content"),
        summary="Summary of page 1",
    )


@pytest.fixture
def sample_document_summary_list():
    return [
        DocumentSummaryModel(
            data=DocumentPageModel(page_number=1, content="Page 1 content"),
            summary="Summary of page 1. ",
        ),
        DocumentSummaryModel(
            data=DocumentPageModel(page_number=2, content="Page 2 content"),
            summary="Summary of page 2. ",
        ),
    ]


# ---------------------------------------------------------------------------
# upload_file_service
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadFileService:
    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_success(
        self,
        mock_del_cache,
        mock_files_collection,
        mock_cloudinary_upload,
        mock_chroma_client,
    ):
        mock_cloudinary_upload.return_value = {
            "secure_url": "https://res.cloudinary.com/test/uploaded.pdf"
        }
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = ObjectId()
        mock_files_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        _, mock_chroma_col = mock_chroma_client

        with patch(
            "app.services.file_service.generate_file_summary",
            new_callable=AsyncMock,
            return_value="This is a summary",
        ):
            file = MagicMock()
            file.filename = "report.pdf"
            file.content_type = "application/pdf"
            file.read = AsyncMock(return_value=b"x" * 100)

            result = await upload_file_service(
                file=file,
                user_id="user-abc",
                conversation_id="conv-1",
            )

        assert result["url"] == "https://res.cloudinary.com/test/uploaded.pdf"
        assert result["filename"] == "report.pdf"
        assert result["description"] == "This is a summary"
        assert result["type"] == "application/pdf"
        assert "file_id" in result

    async def test_missing_filename_raises_400(self):
        file = MagicMock()
        file.filename = None
        file.content_type = "application/pdf"

        with pytest.raises(HTTPException) as exc_info:
            await upload_file_service(file=file, user_id="user-abc")
        assert exc_info.value.status_code == 400
        assert "Filename is required" in exc_info.value.detail

    async def test_missing_filename_empty_string_raises_400(self):
        file = MagicMock()
        file.filename = ""
        file.content_type = "application/pdf"

        with pytest.raises(HTTPException) as exc_info:
            await upload_file_service(file=file, user_id="user-abc")
        assert exc_info.value.status_code == 400

    async def test_missing_content_type_raises_400(self):
        file = MagicMock()
        file.filename = "test.pdf"
        file.content_type = None

        with pytest.raises(HTTPException) as exc_info:
            await upload_file_service(file=file, user_id="user-abc")
        assert exc_info.value.status_code == 400
        assert "Content type is required" in exc_info.value.detail

    async def test_empty_content_type_raises_400(self):
        file = MagicMock()
        file.filename = "test.pdf"
        file.content_type = ""

        with pytest.raises(HTTPException) as exc_info:
            await upload_file_service(file=file, user_id="user-abc")
        assert exc_info.value.status_code == 400

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_file_too_large_raises_400(self, mock_del_cache):
        file = MagicMock()
        file.filename = "huge.pdf"
        file.content_type = "application/pdf"
        # 11 MB file
        file.read = AsyncMock(return_value=b"x" * (11 * 1024 * 1024))

        with pytest.raises(HTTPException) as exc_info:
            await upload_file_service(file=file, user_id="user-abc")
        assert exc_info.value.status_code == 400
        assert "10 MB" in exc_info.value.detail

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_file_exactly_10mb_succeeds(
        self,
        mock_del_cache,
        mock_files_collection,
        mock_cloudinary_upload,
        mock_chroma_client,
    ):
        """File at exactly 10 MB boundary should pass the size check."""
        mock_cloudinary_upload.return_value = {
            "secure_url": "https://res.cloudinary.com/test/uploaded.pdf"
        }
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = ObjectId()
        mock_files_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        with patch(
            "app.services.file_service.generate_file_summary",
            new_callable=AsyncMock,
            return_value="summary",
        ):
            file = MagicMock()
            file.filename = "big.pdf"
            file.content_type = "application/pdf"
            file.read = AsyncMock(return_value=b"x" * (10 * 1024 * 1024))

            result = await upload_file_service(file=file, user_id="user-abc")
        assert "file_id" in result

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_cloudinary_missing_secure_url_raises_500(
        self,
        mock_del_cache,
        mock_cloudinary_upload,
    ):
        mock_cloudinary_upload.return_value = {}  # No secure_url

        with patch(
            "app.services.file_service.generate_file_summary",
            new_callable=AsyncMock,
            return_value="summary",
        ):
            file = MagicMock()
            file.filename = "test.pdf"
            file.content_type = "application/pdf"
            file.read = AsyncMock(return_value=b"small content")

            with pytest.raises(HTTPException) as exc_info:
                await upload_file_service(file=file, user_id="user-abc")
            assert exc_info.value.status_code == 500
            assert "Invalid response" in exc_info.value.detail

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_cloudinary_exception_raises_500(
        self,
        mock_del_cache,
        mock_cloudinary_upload,
    ):
        mock_cloudinary_upload.side_effect = Exception("Cloudinary connection error")

        with patch(
            "app.services.file_service.generate_file_summary",
            new_callable=AsyncMock,
            return_value="summary",
        ):
            file = MagicMock()
            file.filename = "test.pdf"
            file.content_type = "application/pdf"
            file.read = AsyncMock(return_value=b"small content")

            with pytest.raises(HTTPException) as exc_info:
                await upload_file_service(file=file, user_id="user-abc")
            assert exc_info.value.status_code == 500
            assert "Failed to upload file" in exc_info.value.detail

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_db_insertion_fails_raises_500(
        self,
        mock_del_cache,
        mock_files_collection,
        mock_cloudinary_upload,
        mock_chroma_client,
    ):
        mock_cloudinary_upload.return_value = {
            "secure_url": "https://res.cloudinary.com/test/uploaded.pdf"
        }
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = None
        mock_files_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        _, mock_chroma_col = mock_chroma_client

        with patch(
            "app.services.file_service.generate_file_summary",
            new_callable=AsyncMock,
            return_value="summary",
        ):
            file = MagicMock()
            file.filename = "test.pdf"
            file.content_type = "application/pdf"
            file.read = AsyncMock(return_value=b"content")

            with pytest.raises(HTTPException) as exc_info:
                await upload_file_service(file=file, user_id="user-abc")
            assert exc_info.value.status_code == 500

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_success_without_conversation_id(
        self,
        mock_del_cache,
        mock_files_collection,
        mock_cloudinary_upload,
        mock_chroma_client,
    ):
        mock_cloudinary_upload.return_value = {
            "secure_url": "https://res.cloudinary.com/test/uploaded.pdf"
        }
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = ObjectId()
        mock_files_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        with patch(
            "app.services.file_service.generate_file_summary",
            new_callable=AsyncMock,
            return_value="This is a summary",
        ):
            file = MagicMock()
            file.filename = "report.pdf"
            file.content_type = "application/pdf"
            file.read = AsyncMock(return_value=b"x" * 100)

            result = await upload_file_service(
                file=file,
                user_id="user-abc",
                conversation_id=None,
            )

        assert result["filename"] == "report.pdf"
        assert "file_id" in result

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_success_with_list_summary(
        self,
        mock_del_cache,
        mock_files_collection,
        mock_cloudinary_upload,
        mock_chroma_client,
        sample_document_summary_list,
    ):
        mock_cloudinary_upload.return_value = {
            "secure_url": "https://res.cloudinary.com/test/uploaded.pdf"
        }
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = ObjectId()
        mock_files_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        with patch(
            "app.services.file_service.generate_file_summary",
            new_callable=AsyncMock,
            return_value=sample_document_summary_list,
        ):
            file = MagicMock()
            file.filename = "multipage.pdf"
            file.content_type = "application/pdf"
            file.read = AsyncMock(return_value=b"x" * 100)

            result = await upload_file_service(
                file=file,
                user_id="user-abc",
            )

        assert "Summary of page 1" in result["description"]
        assert "Summary of page 2" in result["description"]


# ---------------------------------------------------------------------------
# _process_file_summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessFileSummary:
    def test_string_input(self):
        summary, formatted = _process_file_summary("Simple text summary")
        assert summary == "Simple text summary"
        assert formatted is None

    def test_list_input(self, sample_document_summary_list):
        summary, formatted = _process_file_summary(sample_document_summary_list)
        assert "Summary of page 1" in summary
        assert "Summary of page 2" in summary
        assert isinstance(formatted, list)
        assert len(formatted) == 2
        assert formatted[0]["summary"] == "Summary of page 1. "
        assert formatted[0]["data"]["page_number"] == 1

    def test_document_summary_model_input(self, sample_document_summary_model):
        summary, formatted = _process_file_summary(sample_document_summary_model)
        assert summary == "Summary of page 1"
        assert isinstance(formatted, dict)
        assert formatted["summary"] == "Summary of page 1"
        assert formatted["data"]["page_number"] == 1

    def test_invalid_type_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _process_file_summary(12345)
        assert exc_info.value.status_code == 400
        assert "Invalid file description format" in exc_info.value.detail

    def test_none_input_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _process_file_summary(None)
        assert exc_info.value.status_code == 400

    def test_dict_input_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _process_file_summary({"summary": "test"})
        assert exc_info.value.status_code == 400

    def test_empty_string_input(self):
        summary, formatted = _process_file_summary("")
        assert summary == ""
        assert formatted is None

    def test_empty_list_input(self):
        summary, formatted = _process_file_summary([])
        assert summary == ""
        assert isinstance(formatted, list)
        assert len(formatted) == 0


# ---------------------------------------------------------------------------
# _store_in_mongodb
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStoreInMongodb:
    async def test_success(self, mock_files_collection):
        mock_result = MagicMock()
        mock_result.inserted_id = ObjectId()
        mock_files_collection.insert_one = AsyncMock(return_value=mock_result)

        await _store_in_mongodb({"file_id": "f-1", "filename": "test.pdf"})

        mock_files_collection.insert_one.assert_awaited_once_with(
            document={"file_id": "f-1", "filename": "test.pdf"}
        )

    async def test_insertion_fails_raises_500(self, mock_files_collection):
        mock_result = MagicMock()
        mock_result.inserted_id = None
        mock_files_collection.insert_one = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await _store_in_mongodb({"file_id": "f-1"})
        assert exc_info.value.status_code == 500
        assert "Failed to store file metadata" in exc_info.value.detail

    async def test_exception_propagates(self, mock_files_collection):
        mock_files_collection.insert_one = AsyncMock(
            side_effect=Exception("Connection lost")
        )

        with pytest.raises(Exception, match="Connection lost"):
            await _store_in_mongodb({"file_id": "f-1"})


# ---------------------------------------------------------------------------
# _store_in_chromadb
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStoreInChromadb:
    async def test_list_description_multi_page(
        self, mock_chroma_client, sample_document_summary_list
    ):
        mock_chroma_cls, mock_chroma_col = mock_chroma_client

        await _store_in_chromadb(
            file_id="f-1",
            user_id="user-abc",
            filename="doc.pdf",
            content_type="application/pdf",
            file_description=sample_document_summary_list,
            conversation_id="conv-1",
        )

        mock_chroma_col.aadd_documents.assert_awaited_once()
        call_kwargs = mock_chroma_col.aadd_documents.call_args
        documents = call_kwargs.kwargs.get("documents") or call_kwargs[1].get(
            "documents"
        )
        ids = call_kwargs.kwargs.get("ids") or call_kwargs[1].get("ids")
        assert len(documents) == 2
        assert len(ids) == 2
        assert documents[0].page_content == "Summary of page 1. "
        assert documents[0].metadata["page_number"] == 1
        assert documents[0].metadata["conversation_id"] == "conv-1"
        assert documents[1].page_content == "Summary of page 2. "
        assert documents[1].metadata["page_number"] == 2

    async def test_string_description(self, mock_chroma_client):
        mock_chroma_cls, mock_chroma_col = mock_chroma_client

        await _store_in_chromadb(
            file_id="f-1",
            user_id="user-abc",
            filename="doc.txt",
            content_type="text/plain",
            file_description="A plain text description",
        )

        mock_chroma_col.aadd_documents.assert_awaited_once()
        call_kwargs = mock_chroma_col.aadd_documents.call_args
        documents = call_kwargs.kwargs.get("documents") or call_kwargs[1].get(
            "documents"
        )
        ids = call_kwargs.kwargs.get("ids") or call_kwargs[1].get("ids")
        assert len(documents) == 1
        assert documents[0].page_content == "A plain text description"
        assert ids == ["f-1"]
        # No conversation_id when not provided
        assert "conversation_id" not in documents[0].metadata

    async def test_document_summary_model_description(
        self, mock_chroma_client, sample_document_summary_model
    ):
        mock_chroma_cls, mock_chroma_col = mock_chroma_client

        await _store_in_chromadb(
            file_id="f-1",
            user_id="user-abc",
            filename="doc.pdf",
            content_type="application/pdf",
            file_description=sample_document_summary_model,
        )

        mock_chroma_col.aadd_documents.assert_awaited_once()
        call_kwargs = mock_chroma_col.aadd_documents.call_args
        documents = call_kwargs.kwargs.get("documents") or call_kwargs[1].get(
            "documents"
        )
        assert len(documents) == 1
        assert documents[0].page_content == "Summary of page 1"

    async def test_chromadb_fails_logged_not_raised(self, mock_chroma_client):
        mock_chroma_cls, mock_chroma_col = mock_chroma_client
        mock_chroma_col.aadd_documents = AsyncMock(
            side_effect=Exception("ChromaDB down")
        )

        # Should not raise
        await _store_in_chromadb(
            file_id="f-1",
            user_id="user-abc",
            filename="doc.pdf",
            content_type="application/pdf",
            file_description="summary",
        )

    async def test_chromadb_client_init_fails_logged_not_raised(self):
        with patch(
            "app.services.file_service.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            side_effect=Exception("ChromaDB init failed"),
        ):
            # Should not raise
            await _store_in_chromadb(
                file_id="f-1",
                user_id="user-abc",
                filename="doc.pdf",
                content_type="application/pdf",
                file_description="summary",
            )

    async def test_list_description_without_conversation_id(
        self, mock_chroma_client, sample_document_summary_list
    ):
        mock_chroma_cls, mock_chroma_col = mock_chroma_client

        await _store_in_chromadb(
            file_id="f-1",
            user_id="user-abc",
            filename="doc.pdf",
            content_type="application/pdf",
            file_description=sample_document_summary_list,
            conversation_id=None,
        )

        call_kwargs = mock_chroma_col.aadd_documents.call_args
        documents = call_kwargs.kwargs.get("documents") or call_kwargs[1].get(
            "documents"
        )
        for doc in documents:
            assert "conversation_id" not in doc.metadata

    async def test_string_description_with_conversation_id(self, mock_chroma_client):
        mock_chroma_cls, mock_chroma_col = mock_chroma_client

        await _store_in_chromadb(
            file_id="f-1",
            user_id="user-abc",
            filename="doc.txt",
            content_type="text/plain",
            file_description="A description",
            conversation_id="conv-99",
        )

        call_kwargs = mock_chroma_col.aadd_documents.call_args
        documents = call_kwargs.kwargs.get("documents") or call_kwargs[1].get(
            "documents"
        )
        assert documents[0].metadata["conversation_id"] == "conv-99"


# ---------------------------------------------------------------------------
# update_file_in_chromadb
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateFileInChromadb:
    async def test_delete_and_store_success(self, mock_chroma_client):
        mock_chroma_cls, mock_chroma_col = mock_chroma_client

        with patch(
            "app.services.file_service._store_in_chromadb",
            new_callable=AsyncMock,
        ) as mock_store:
            await update_file_in_chromadb(
                file_id="f-1",
                user_id="user-abc",
                filename="doc.pdf",
                content_type="application/pdf",
                file_description="updated summary",
                conversation_id="conv-1",
            )

            mock_chroma_col.adelete.assert_awaited_once_with(ids=["f-1"])
            mock_store.assert_awaited_once_with(
                file_id="f-1",
                user_id="user-abc",
                filename="doc.pdf",
                content_type="application/pdf",
                file_description="updated summary",
                conversation_id="conv-1",
            )

    async def test_delete_fails_continues_to_store(self, mock_chroma_client):
        mock_chroma_cls, mock_chroma_col = mock_chroma_client
        mock_chroma_col.adelete = AsyncMock(side_effect=Exception("Delete error"))

        with patch(
            "app.services.file_service._store_in_chromadb",
            new_callable=AsyncMock,
        ) as mock_store:
            await update_file_in_chromadb(
                file_id="f-1",
                user_id="user-abc",
                filename="doc.pdf",
                content_type="application/pdf",
                file_description="updated summary",
            )

            # Store should still be called even though delete failed
            mock_store.assert_awaited_once()

    async def test_store_fails_logged_not_raised(self, mock_chroma_client):
        mock_chroma_cls, mock_chroma_col = mock_chroma_client

        with patch(
            "app.services.file_service._store_in_chromadb",
            new_callable=AsyncMock,
            side_effect=Exception("Store error"),
        ):
            # Should not raise
            await update_file_in_chromadb(
                file_id="f-1",
                user_id="user-abc",
                filename="doc.pdf",
                content_type="application/pdf",
                file_description="updated summary",
            )

    async def test_chroma_client_init_fails_still_calls_store(self):
        """When get_langchain_client fails in the inner try, the delete is
        skipped but _store_in_chromadb is still called because the inner
        except only catches the delete failure."""
        with patch(
            "app.services.file_service.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            side_effect=Exception("ChromaDB unavailable"),
        ):
            with patch(
                "app.services.file_service._store_in_chromadb",
                new_callable=AsyncMock,
            ) as mock_store:
                await update_file_in_chromadb(
                    file_id="f-1",
                    user_id="user-abc",
                    filename="doc.pdf",
                    content_type="application/pdf",
                    file_description="summary",
                )
                # _store_in_chromadb IS called because the inner try/except
                # catches the get_langchain_client error and continues.
                mock_store.assert_awaited_once()


# ---------------------------------------------------------------------------
# fetch_files
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchFiles:
    async def test_no_user_id_returns_context_unchanged(self):
        context: Dict[str, Any] = {"query_text": "hello"}
        result = await fetch_files(context)
        assert result is context
        assert "files_added" not in result

    async def test_empty_last_message_returns_early(self):
        context: Dict[str, Any] = {
            "user_id": "user-abc",
            "last_message": None,
            "query_text": "hello",
        }
        result = await fetch_files(context)
        assert result["files_added"] is False

    async def test_empty_string_last_message_returns_early(self):
        context: Dict[str, Any] = {
            "user_id": "user-abc",
            "last_message": "",
            "query_text": "hello",
        }
        result = await fetch_files(context)
        assert result["files_added"] is False

    async def test_with_explicit_file_ids_from_db_lookup(self, mock_files_collection):
        """When fileIds are provided but not in fileData, files are fetched from DB."""
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "_id": ObjectId(),
                    "file_id": "f-1",
                    "filename": "doc.pdf",
                    "url": "https://example.com/doc.pdf",
                    "description": "A doc",
                    "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                    "updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                }
            ]
        )
        mock_files_collection.find = MagicMock(return_value=mock_cursor)

        context: Dict[str, Any] = {
            "user_id": "user-abc",
            "last_message": {"content": "Check this file"},
            "query_text": "ab",
            "fileIds": ["f-1"],
            "fileData": [],
            "conversation_id": None,
        }
        result = await fetch_files(context)
        assert result["files_added"] is True
        assert len(result["files_data"]) == 1
        assert result["files_data"][0]["file_id"] == "f-1"

    async def test_with_explicit_file_ids_missing_from_file_data(
        self, mock_files_collection
    ):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "_id": ObjectId(),
                    "file_id": "f-2",
                    "filename": "report.pdf",
                    "url": "https://example.com/report.pdf",
                    "description": "A report",
                    "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                    "updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                }
            ]
        )
        mock_files_collection.find = MagicMock(return_value=mock_cursor)

        context: Dict[str, Any] = {
            "user_id": "user-abc",
            "last_message": {"content": "Check this file"},
            "query_text": "ab",
            "fileIds": ["f-2"],
            "fileData": [],
            "conversation_id": None,
        }
        result = await fetch_files(context)
        assert result["files_added"] is True
        assert any(f["file_id"] == "f-2" for f in result["files_data"])

    async def test_with_semantic_search(self, mock_search_documents):
        mock_search_documents.return_value = [
            {
                "file_id": "f-semantic",
                "url": "https://example.com/semantic.pdf",
                "filename": "semantic.pdf",
                "description": "Relevant file",
                "content_type": "application/pdf",
                "similarity_score": 0.95,
            }
        ]
        context: Dict[str, Any] = {
            "user_id": "user-abc",
            "last_message": {"content": "Tell me about machine learning"},
            "query_text": "Tell me about machine learning",
            "fileIds": [],
            "fileData": [],
            "conversation_id": "conv-1",
        }
        result = await fetch_files(context)
        assert result["files_added"] is True
        assert any(f["file_id"] == "f-semantic" for f in result["files_data"])

    async def test_semantic_search_fails_continues(self, mock_search_documents):
        mock_search_documents.side_effect = Exception("Search engine down")

        context: Dict[str, Any] = {
            "user_id": "user-abc",
            "last_message": {"content": "Tell me about something"},
            "query_text": "Tell me about something",
            "fileIds": [],
            "fileData": [],
            "conversation_id": None,
        }
        result = await fetch_files(context)
        # Should not crash; no files found
        assert result["files_added"] is False

    async def test_short_query_skips_semantic_search(self, mock_search_documents):
        context: Dict[str, Any] = {
            "user_id": "user-abc",
            "last_message": {"content": "hi"},
            "query_text": "hi",
            "fileIds": [],
            "fileData": [],
            "conversation_id": None,
        }
        result = await fetch_files(context)
        mock_search_documents.assert_not_awaited()
        assert result["files_added"] is False

    async def test_query_exactly_3_chars_skips_semantic_search(
        self, mock_search_documents
    ):
        context: Dict[str, Any] = {
            "user_id": "user-abc",
            "last_message": {"content": "abc"},
            "query_text": "abc",
            "fileIds": [],
            "fileData": [],
            "conversation_id": None,
        }
        await fetch_files(context)
        mock_search_documents.assert_not_awaited()

    async def test_query_4_chars_triggers_semantic_search(self, mock_search_documents):
        mock_search_documents.return_value = []
        context: Dict[str, Any] = {
            "user_id": "user-abc",
            "last_message": {"content": "abcd"},
            "query_text": "abcd",
            "fileIds": [],
            "fileData": [],
            "conversation_id": None,
        }
        await fetch_files(context)
        mock_search_documents.assert_awaited_once()

    async def test_semantic_results_deduplicated_with_explicit(
        self, mock_files_collection, mock_search_documents
    ):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "_id": ObjectId(),
                    "file_id": "f-1",
                    "filename": "doc.pdf",
                    "url": "https://example.com/doc.pdf",
                    "description": "A doc",
                    "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                    "updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                }
            ]
        )
        mock_files_collection.find = MagicMock(return_value=mock_cursor)

        mock_search_documents.return_value = [
            {
                "file_id": "f-1",  # same as explicit
                "url": "https://example.com/doc.pdf",
                "filename": "doc.pdf",
                "description": "duplicate",
                "content_type": "application/pdf",
                "similarity_score": 0.9,
            },
            {
                "file_id": "f-new",
                "url": "https://example.com/new.pdf",
                "filename": "new.pdf",
                "description": "new file",
                "content_type": "application/pdf",
                "similarity_score": 0.85,
            },
        ]
        context: Dict[str, Any] = {
            "user_id": "user-abc",
            "last_message": {"content": "Something about documents and more"},
            "query_text": "Something about documents and more",
            "fileIds": ["f-1"],
            "fileData": [],
            "conversation_id": None,
        }
        result = await fetch_files(context)
        assert result["files_added"] is True
        file_ids = [f["file_id"] for f in result["files_data"]]
        assert file_ids.count("f-1") == 1
        assert "f-new" in file_ids

    async def test_no_files_found(self, mock_search_documents):
        mock_search_documents.return_value = []
        context: Dict[str, Any] = {
            "user_id": "user-abc",
            "last_message": {"content": "Tell me about something specific"},
            "query_text": "Tell me about something specific",
            "fileIds": [],
            "fileData": [],
            "conversation_id": None,
        }
        result = await fetch_files(context)
        assert result["files_added"] is False

    async def test_file_content_appended_to_message(self):
        file_data = FileData(
            fileId="f-1",
            filename="doc.pdf",
            url="https://example.com/doc.pdf",
            type="application/pdf",
        )
        context: Dict[str, Any] = {
            "user_id": "user-abc",
            "last_message": {"content": "Original message"},
            "query_text": "ab",
            "fileIds": ["f-1"],
            "fileData": [file_data],
            "conversation_id": None,
        }
        result = await fetch_files(context)
        assert "## File Information" in result["last_message"]["content"]
        assert "Uploaded Files" in result["last_message"]["content"]

    async def test_semantic_files_section_in_formatted_output(
        self, mock_search_documents
    ):
        mock_search_documents.return_value = [
            {
                "file_id": "f-sem",
                "url": "https://example.com/sem.pdf",
                "filename": "semantic.pdf",
                "description": "Relevant doc",
                "content_type": "application/pdf",
                "similarity_score": 0.8,
            }
        ]
        context: Dict[str, Any] = {
            "user_id": "user-abc",
            "last_message": {"content": "Tell me about something"},
            "query_text": "Tell me about something",
            "fileIds": [],
            "fileData": [],
            "conversation_id": None,
        }
        result = await fetch_files(context)
        assert "Relevant Files" in result["last_message"]["content"]


# ---------------------------------------------------------------------------
# delete_file_service
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteFileService:
    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_success(
        self,
        mock_del_cache,
        mock_files_collection,
        mock_cloudinary_destroy,
        mock_chroma_client,
    ):
        mock_files_collection.find_one = AsyncMock(
            return_value={
                "file_id": "f-1",
                "user_id": "user-abc",
                "filename": "doc.pdf",
                "public_id": "file_f-1_doc.pdf",
            }
        )
        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 1
        mock_files_collection.delete_one = AsyncMock(return_value=mock_delete_result)
        mock_cloudinary_destroy.return_value = {"result": "ok"}

        _, mock_chroma_col = mock_chroma_client

        result = await delete_file_service(file_id="f-1", user_id="user-abc")

        assert result["message"] == "File deleted successfully"
        assert result["file_id"] == "f-1"
        assert result["filename"] == "doc.pdf"
        mock_files_collection.delete_one.assert_awaited_once()
        mock_cloudinary_destroy.assert_called_once_with("file_f-1_doc.pdf")
        mock_chroma_col.adelete.assert_awaited_once_with(ids=["f-1"])

    async def test_user_id_none_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            await delete_file_service(file_id="f-1", user_id=None)
        assert exc_info.value.status_code == 400
        assert "User ID is required" in exc_info.value.detail

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_file_not_found_raises_404(
        self, mock_del_cache, mock_files_collection
    ):
        mock_files_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await delete_file_service(file_id="f-nonexistent", user_id="user-abc")
        assert exc_info.value.status_code == 404

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_mongo_delete_count_zero_raises_404(
        self, mock_del_cache, mock_files_collection
    ):
        mock_files_collection.find_one = AsyncMock(
            return_value={
                "file_id": "f-1",
                "user_id": "user-abc",
                "filename": "doc.pdf",
                "public_id": "pub-id",
            }
        )
        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 0
        mock_files_collection.delete_one = AsyncMock(return_value=mock_delete_result)

        with pytest.raises(HTTPException) as exc_info:
            await delete_file_service(file_id="f-1", user_id="user-abc")
        assert exc_info.value.status_code == 404

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_cloudinary_fails_continues(
        self,
        mock_del_cache,
        mock_files_collection,
        mock_cloudinary_destroy,
        mock_chroma_client,
    ):
        mock_files_collection.find_one = AsyncMock(
            return_value={
                "file_id": "f-1",
                "user_id": "user-abc",
                "filename": "doc.pdf",
                "public_id": "pub-id",
            }
        )
        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 1
        mock_files_collection.delete_one = AsyncMock(return_value=mock_delete_result)
        mock_cloudinary_destroy.side_effect = Exception("Cloudinary error")

        _, mock_chroma_col = mock_chroma_client

        # Should NOT raise
        result = await delete_file_service(file_id="f-1", user_id="user-abc")
        assert result["message"] == "File deleted successfully"

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_cloudinary_non_ok_result_continues(
        self,
        mock_del_cache,
        mock_files_collection,
        mock_cloudinary_destroy,
        mock_chroma_client,
    ):
        mock_files_collection.find_one = AsyncMock(
            return_value={
                "file_id": "f-1",
                "user_id": "user-abc",
                "filename": "doc.pdf",
                "public_id": "pub-id",
            }
        )
        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 1
        mock_files_collection.delete_one = AsyncMock(return_value=mock_delete_result)
        mock_cloudinary_destroy.return_value = {"result": "not found"}

        _, mock_chroma_col = mock_chroma_client

        result = await delete_file_service(file_id="f-1", user_id="user-abc")
        assert result["message"] == "File deleted successfully"

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_chromadb_fails_continues(
        self,
        mock_del_cache,
        mock_files_collection,
        mock_cloudinary_destroy,
        mock_chroma_client,
    ):
        mock_files_collection.find_one = AsyncMock(
            return_value={
                "file_id": "f-1",
                "user_id": "user-abc",
                "filename": "doc.pdf",
                "public_id": "pub-id",
            }
        )
        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 1
        mock_files_collection.delete_one = AsyncMock(return_value=mock_delete_result)
        mock_cloudinary_destroy.return_value = {"result": "ok"}

        _, mock_chroma_col = mock_chroma_client
        mock_chroma_col.adelete = AsyncMock(side_effect=Exception("ChromaDB error"))

        result = await delete_file_service(file_id="f-1", user_id="user-abc")
        assert result["message"] == "File deleted successfully"

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_no_public_id_skips_cloudinary(
        self,
        mock_del_cache,
        mock_files_collection,
        mock_cloudinary_destroy,
        mock_chroma_client,
    ):
        mock_files_collection.find_one = AsyncMock(
            return_value={
                "file_id": "f-1",
                "user_id": "user-abc",
                "filename": "doc.pdf",
                "public_id": None,
            }
        )
        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 1
        mock_files_collection.delete_one = AsyncMock(return_value=mock_delete_result)

        _, mock_chroma_col = mock_chroma_client

        result = await delete_file_service(file_id="f-1", user_id="user-abc")
        assert result["message"] == "File deleted successfully"
        mock_cloudinary_destroy.assert_not_called()

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_missing_public_id_key_skips_cloudinary(
        self,
        mock_del_cache,
        mock_files_collection,
        mock_cloudinary_destroy,
        mock_chroma_client,
    ):
        mock_files_collection.find_one = AsyncMock(
            return_value={
                "file_id": "f-1",
                "user_id": "user-abc",
                "filename": "doc.pdf",
                # public_id key missing entirely
            }
        )
        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 1
        mock_files_collection.delete_one = AsyncMock(return_value=mock_delete_result)

        _, mock_chroma_col = mock_chroma_client

        result = await delete_file_service(file_id="f-1", user_id="user-abc")
        assert result["message"] == "File deleted successfully"
        mock_cloudinary_destroy.assert_not_called()

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_returns_unknown_when_filename_missing(
        self,
        mock_del_cache,
        mock_files_collection,
        mock_cloudinary_destroy,
        mock_chroma_client,
    ):
        mock_files_collection.find_one = AsyncMock(
            return_value={
                "file_id": "f-1",
                "user_id": "user-abc",
                "public_id": "pub-id",
                # filename missing
            }
        )
        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 1
        mock_files_collection.delete_one = AsyncMock(return_value=mock_delete_result)
        mock_cloudinary_destroy.return_value = {"result": "ok"}

        _, mock_chroma_col = mock_chroma_client

        result = await delete_file_service(file_id="f-1", user_id="user-abc")
        assert result["filename"] == "Unknown"


# ---------------------------------------------------------------------------
# update_file_service
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateFileService:
    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_file_not_found_raises_404(
        self, mock_del_cache, mock_files_collection
    ):
        mock_files_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await update_file_service(
                file_id="f-missing",
                user_id="user-abc",
                update_data={"filename": "new.pdf"},
            )
        assert exc_info.value.status_code == 404

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_success_without_file_content(
        self, mock_del_cache, mock_files_collection
    ):
        original_file = {
            "_id": ObjectId(),
            "file_id": "f-1",
            "user_id": "user-abc",
            "filename": "old.pdf",
            "type": "application/pdf",
            "description": "Old description",
            "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        }
        updated_file = {
            **original_file,
            "filename": "new.pdf",
            "updated_at": datetime(2025, 6, 1, tzinfo=timezone.utc),
        }

        mock_files_collection.find_one = AsyncMock(
            side_effect=[original_file, updated_file]
        )
        mock_update_result = MagicMock()
        mock_update_result.modified_count = 1
        mock_files_collection.update_one = AsyncMock(return_value=mock_update_result)

        result = await update_file_service(
            file_id="f-1",
            user_id="user-abc",
            update_data={"filename": "new.pdf"},
        )

        assert result["filename"] == "new.pdf"
        mock_files_collection.update_one.assert_awaited_once()

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_with_file_content_regenerates_description(
        self, mock_del_cache, mock_files_collection, mock_chroma_client
    ):
        original_file = {
            "_id": ObjectId(),
            "file_id": "f-1",
            "user_id": "user-abc",
            "filename": "doc.pdf",
            "type": "application/pdf",
            "description": "Old description",
            "conversation_id": "conv-1",
            "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        }
        updated_file = {
            **original_file,
            "description": "New summary from content",
        }

        mock_files_collection.find_one = AsyncMock(
            side_effect=[original_file, updated_file]
        )
        mock_update_result = MagicMock()
        mock_update_result.modified_count = 1
        mock_files_collection.update_one = AsyncMock(return_value=mock_update_result)

        with patch(
            "app.services.file_service.generate_file_summary",
            new_callable=AsyncMock,
            return_value="New summary from content",
        ):
            with patch(
                "app.services.file_service.update_file_in_chromadb",
                new_callable=AsyncMock,
            ) as mock_chroma_update:
                result = await update_file_service(
                    file_id="f-1",
                    user_id="user-abc",
                    update_data={},
                    file_content=b"new file bytes",
                    conversation_id="conv-1",
                )

        assert result["description"] == "New summary from content"
        mock_chroma_update.assert_awaited_once()

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_file_content_generation_fails_raises_500(
        self, mock_del_cache, mock_files_collection
    ):
        mock_files_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId(),
                "file_id": "f-1",
                "user_id": "user-abc",
                "filename": "doc.pdf",
                "type": "application/pdf",
            }
        )

        with patch(
            "app.services.file_service.generate_file_summary",
            new_callable=AsyncMock,
            side_effect=Exception("LLM unavailable"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await update_file_service(
                    file_id="f-1",
                    user_id="user-abc",
                    update_data={},
                    file_content=b"content",
                )
            assert exc_info.value.status_code == 500
            assert "Failed to process file" in exc_info.value.detail

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_chromadb_update_fails_continues(
        self, mock_del_cache, mock_files_collection
    ):
        original_file = {
            "_id": ObjectId(),
            "file_id": "f-1",
            "user_id": "user-abc",
            "filename": "doc.pdf",
            "type": "application/pdf",
            "description": "old",
            "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        }
        updated_file = {**original_file, "description": "new desc"}

        mock_files_collection.find_one = AsyncMock(
            side_effect=[original_file, updated_file]
        )
        mock_update_result = MagicMock()
        mock_update_result.modified_count = 1
        mock_files_collection.update_one = AsyncMock(return_value=mock_update_result)

        with patch(
            "app.services.file_service.update_file_in_chromadb",
            new_callable=AsyncMock,
            side_effect=Exception("ChromaDB down"),
        ):
            # Should NOT raise
            result = await update_file_service(
                file_id="f-1",
                user_id="user-abc",
                update_data={"description": "new desc"},
            )
        assert result["description"] == "new desc"

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_file_not_found_after_update_raises_404(
        self, mock_del_cache, mock_files_collection
    ):
        original_file = {
            "_id": ObjectId(),
            "file_id": "f-1",
            "user_id": "user-abc",
            "filename": "doc.pdf",
            "type": "application/pdf",
        }

        # First find_one returns original, second returns None
        mock_files_collection.find_one = AsyncMock(side_effect=[original_file, None])
        mock_update_result = MagicMock()
        mock_update_result.modified_count = 1
        mock_files_collection.update_one = AsyncMock(return_value=mock_update_result)

        with pytest.raises(HTTPException) as exc_info:
            await update_file_service(
                file_id="f-1",
                user_id="user-abc",
                update_data={"filename": "new.pdf"},
            )
        assert exc_info.value.status_code == 404
        assert "not found after update" in exc_info.value.detail

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_no_conversation_id_uses_existing(
        self, mock_del_cache, mock_files_collection
    ):
        original_file = {
            "_id": ObjectId(),
            "file_id": "f-1",
            "user_id": "user-abc",
            "filename": "doc.pdf",
            "type": "application/pdf",
            "conversation_id": "conv-existing",
            "description": "desc",
            "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        }
        updated_file = {**original_file, "description": "updated desc"}

        mock_files_collection.find_one = AsyncMock(
            side_effect=[original_file, updated_file]
        )
        mock_update_result = MagicMock()
        mock_update_result.modified_count = 1
        mock_files_collection.update_one = AsyncMock(return_value=mock_update_result)

        with patch(
            "app.services.file_service.update_file_in_chromadb",
            new_callable=AsyncMock,
        ) as mock_chroma_update:
            await update_file_service(
                file_id="f-1",
                user_id="user-abc",
                update_data={"description": "updated desc"},
                conversation_id=None,
            )

        # Verify chromadb was called with existing conversation_id
        mock_chroma_update.assert_awaited_once()
        call_kwargs = mock_chroma_update.call_args.kwargs
        assert call_kwargs["conversation_id"] == "conv-existing"

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_modified_count_zero_still_returns(
        self, mock_del_cache, mock_files_collection
    ):
        original_file = {
            "_id": ObjectId(),
            "file_id": "f-1",
            "user_id": "user-abc",
            "filename": "doc.pdf",
            "type": "application/pdf",
            "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        }

        mock_files_collection.find_one = AsyncMock(
            side_effect=[original_file, original_file]
        )
        mock_update_result = MagicMock()
        mock_update_result.modified_count = 0  # no changes
        mock_files_collection.update_one = AsyncMock(return_value=mock_update_result)

        result = await update_file_service(
            file_id="f-1",
            user_id="user-abc",
            update_data={"filename": "doc.pdf"},  # same name
        )
        assert result is not None

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_description_not_updated_skips_chromadb(
        self, mock_del_cache, mock_files_collection
    ):
        """When description is not in update_data, ChromaDB should not be updated."""
        original_file = {
            "_id": ObjectId(),
            "file_id": "f-1",
            "user_id": "user-abc",
            "filename": "doc.pdf",
            "type": "application/pdf",
            "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        }
        updated_file = {**original_file, "filename": "renamed.pdf"}

        mock_files_collection.find_one = AsyncMock(
            side_effect=[original_file, updated_file]
        )
        mock_update_result = MagicMock()
        mock_update_result.modified_count = 1
        mock_files_collection.update_one = AsyncMock(return_value=mock_update_result)

        with patch(
            "app.services.file_service.update_file_in_chromadb",
            new_callable=AsyncMock,
        ) as mock_chroma_update:
            await update_file_service(
                file_id="f-1",
                user_id="user-abc",
                update_data={"filename": "renamed.pdf"},
            )

        mock_chroma_update.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_files
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetFiles:
    @patch(PATCH_GET_CACHE, new_callable=AsyncMock, return_value=None)
    @patch(PATCH_SET_CACHE, new_callable=AsyncMock)
    async def test_with_conversation_id(
        self, mock_set_cache, mock_get_cache, mock_files_collection
    ):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "file_id": "f-1",
                    "filename": "doc.pdf",
                    "url": "https://example.com/doc.pdf",
                    "type": "application/pdf",
                },
                {
                    "file_id": "f-2",
                    "filename": "img.png",
                    "url": "https://example.com/img.png",
                    "type": "image/png",
                },
            ]
        )
        mock_files_collection.find = MagicMock(return_value=mock_cursor)

        result = await get_files(user_id="user-abc", conversation_id="conv-1")

        assert len(result) == 2
        assert isinstance(result[0], FileData)
        assert result[0].fileId == "f-1"
        assert result[1].fileId == "f-2"
        mock_files_collection.find.assert_called_once_with(
            {"user_id": "user-abc", "conversation_id": "conv-1"}
        )

    @patch(PATCH_GET_CACHE, new_callable=AsyncMock, return_value=None)
    @patch(PATCH_SET_CACHE, new_callable=AsyncMock)
    async def test_without_conversation_id(
        self, mock_set_cache, mock_get_cache, mock_files_collection
    ):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "file_id": "f-1",
                    "filename": "doc.pdf",
                    "url": "https://example.com/doc.pdf",
                    "type": "application/pdf",
                },
            ]
        )
        mock_files_collection.find = MagicMock(return_value=mock_cursor)

        result = await get_files(user_id="user-abc", conversation_id=None)

        assert len(result) == 1
        mock_files_collection.find.assert_called_once_with({"user_id": "user-abc"})

    @patch(PATCH_GET_CACHE, new_callable=AsyncMock, return_value=None)
    @patch(PATCH_SET_CACHE, new_callable=AsyncMock)
    async def test_empty_results(
        self, mock_set_cache, mock_get_cache, mock_files_collection
    ):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_files_collection.find = MagicMock(return_value=mock_cursor)

        result = await get_files(user_id="user-abc")

        assert result == []


# ---------------------------------------------------------------------------
# deserialize_file
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeserializeFile:
    def test_valid_file(self):
        file_doc = {
            "file_id": "f-1",
            "filename": "doc.pdf",
            "url": "https://example.com/doc.pdf",
            "type": "application/pdf",
            "message": "Custom message",
        }
        result = deserialize_file(file_doc)
        assert isinstance(result, FileData)
        assert result.fileId == "f-1"
        assert result.filename == "doc.pdf"
        assert result.url == "https://example.com/doc.pdf"
        assert result.type == "application/pdf"
        assert result.message == "Custom message"

    def test_valid_file_with_fileId_key(self):
        file_doc = {
            "fileId": "f-2",
            "filename": "img.png",
            "url": "https://example.com/img.png",
            "type": "image/png",
        }
        result = deserialize_file(file_doc)
        assert result.fileId == "f-2"

    def test_valid_file_defaults(self):
        file_doc = {
            "file_id": "f-1",
            "filename": "doc.pdf",
            "url": "https://example.com/doc.pdf",
            "type": "application/pdf",
        }
        result = deserialize_file(file_doc)
        assert result.message == ""

    def test_missing_file_id_raises_400(self):
        file_doc = {
            "filename": "doc.pdf",
            "url": "https://example.com/doc.pdf",
            "type": "application/pdf",
        }
        with pytest.raises(HTTPException) as exc_info:
            deserialize_file(file_doc)
        assert exc_info.value.status_code == 400
        assert "Invalid file document" in exc_info.value.detail

    def test_empty_file_id_raises_400(self):
        file_doc = {
            "file_id": "",
            "fileId": "",
            "filename": "doc.pdf",
            "url": "https://example.com/doc.pdf",
            "type": "application/pdf",
        }
        with pytest.raises(HTTPException) as exc_info:
            deserialize_file(file_doc)
        assert exc_info.value.status_code == 400

    def test_file_id_prefers_file_id_over_fileId(self):
        file_doc = {
            "file_id": "from-file-id",
            "fileId": "from-fileId",
            "filename": "doc.pdf",
            "url": "https://example.com/doc.pdf",
            "type": "application/pdf",
        }
        result = deserialize_file(file_doc)
        assert result.fileId == "from-file-id"

    def test_falls_back_to_fileId(self):
        file_doc = {
            "file_id": "",
            "fileId": "from-fileId",
            "filename": "doc.pdf",
            "url": "https://example.com/doc.pdf",
            "type": "application/pdf",
        }
        result = deserialize_file(file_doc)
        assert result.fileId == "from-fileId"
