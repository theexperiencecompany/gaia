"""Unit tests for the files service package.

Covers the ``FileService`` upload/update/delete flows plus the store/summaries
helpers they orchestrate. External boundaries (Cloudinary, Mongo, ChromaDB,
the JuiceFS sandbox mirror, the summary LLM) are mocked at the same seams the
production code uses.
"""

from collections.abc import Iterator
import contextlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from fastapi import HTTPException
import pytest

from app.models.files_models import DocumentPageModel, DocumentSummaryModel
from app.services.files.service import FileService
from app.services.files.store import index_file, insert_metadata, reindex_file
from app.services.files.summaries import process_summary
from app.utils.upload_validation import MAX_UPLOAD_BYTES

# The caching decorators import delete_cache/get_cache/set_cache from
# app.decorators.caching, so patches must target that module.
PATCH_DELETE_CACHE = "app.decorators.caching.delete_cache"

# Valid magic bytes for the application/pdf allowlist entry.
PDF_HEADER = b"%PDF-"


def _pdf_bytes(total_size: int = 100) -> bytes:
    return PDF_HEADER + b"x" * (total_size - len(PDF_HEADER))


def _upload_file_mock(
    filename: str | None = "report.pdf",
    content_type: str | None = "application/pdf",
    content: bytes | None = None,
) -> MagicMock:
    file = MagicMock()
    file.filename = filename
    file.content_type = content_type
    file.read = AsyncMock(return_value=content if content is not None else _pdf_bytes())
    return file


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_files_collection() -> Iterator[MagicMock]:
    """One mock behind both module bindings of ``files_collection``.

    ``store.py`` (insert_metadata) and ``service.py`` (find/update/delete) each
    import the collection directly, so both bindings must point at the mock.
    """
    mock_col = MagicMock()
    with (
        patch("app.services.files.service.files_collection", mock_col),
        patch("app.services.files.store.files_collection", mock_col),
    ):
        yield mock_col


@pytest.fixture
def mock_cloudinary_upload() -> Iterator[MagicMock]:
    with patch("app.services.files.store.cloudinary.uploader.upload") as mock_upload:
        yield mock_upload


@pytest.fixture
def mock_cloudinary_destroy() -> Iterator[MagicMock]:
    with patch("app.services.files.store.cloudinary.uploader.destroy") as mock_destroy:
        yield mock_destroy


@pytest.fixture
def mock_chroma_client() -> Iterator[tuple[MagicMock, AsyncMock]]:
    with patch("app.services.files.store.ChromaClient") as mock_chroma:
        mock_collection = AsyncMock()
        mock_chroma.get_langchain_client = AsyncMock(return_value=mock_collection)
        yield mock_chroma, mock_collection


@pytest.fixture
def mock_sandbox_mirror() -> Iterator[tuple[AsyncMock, AsyncMock]]:
    """Mock the JuiceFS projection boundary used by ``FileService.upload``."""
    with (
        patch(
            "app.services.files.service.mirror_upload",
            new_callable=AsyncMock,
            return_value="/workspace/user-uploaded/report.pdf",
        ) as mock_mirror,
        patch(
            "app.services.files.service.write_summary_sidecar",
            new_callable=AsyncMock,
        ) as mock_sidecar,
    ):
        yield mock_mirror, mock_sidecar


@pytest.fixture
def sample_document_summary_model() -> DocumentSummaryModel:
    return DocumentSummaryModel(
        data=DocumentPageModel(page_number=1, content="Page 1 content"),
        summary="Summary of page 1",
    )


@pytest.fixture
def sample_document_summary_list() -> list[DocumentSummaryModel]:
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


def _successful_insert(mock_files_collection: MagicMock) -> None:
    mock_insert_result = MagicMock()
    mock_insert_result.inserted_id = ObjectId()
    mock_files_collection.insert_one = AsyncMock(return_value=mock_insert_result)


@contextlib.contextmanager
def _summary(value: object) -> Iterator[AsyncMock]:
    with patch(
        "app.services.files.service.generate_file_summary",
        new_callable=AsyncMock,
        return_value=value,
    ) as mock_summary:
        yield mock_summary


# ---------------------------------------------------------------------------
# FileService.upload
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFileServiceUpload:
    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_success(
        self,
        mock_del_cache,
        mock_files_collection,
        mock_cloudinary_upload,
        mock_chroma_client,
        mock_sandbox_mirror,
    ):
        mock_cloudinary_upload.return_value = {
            "secure_url": "https://res.cloudinary.com/test/uploaded.pdf"
        }
        _successful_insert(mock_files_collection)
        mock_mirror, mock_sidecar = mock_sandbox_mirror

        with _summary("This is a summary"):
            result = await FileService.upload(
                file=_upload_file_mock(),
                user_id="user-abc",
                conversation_id="conv-1",
            )

        assert result["url"] == "https://res.cloudinary.com/test/uploaded.pdf"
        assert result["filename"] == "report.pdf"
        assert result["description"] == "This is a summary"
        assert result["type"] == "application/pdf"
        assert result["sandbox_path"] == "/workspace/user-uploaded/report.pdf"
        assert "file_id" in result
        mock_mirror.assert_awaited_once()
        mock_sidecar.assert_awaited_once()

    async def test_missing_filename_raises_400(self):
        file = _upload_file_mock(filename=None)

        with pytest.raises(HTTPException) as exc_info:
            await FileService.upload(file=file, user_id="user-abc")
        assert exc_info.value.status_code == 400
        assert "Filename is required" in exc_info.value.detail

    async def test_missing_filename_empty_string_raises_400(self):
        file = _upload_file_mock(filename="")

        with pytest.raises(HTTPException) as exc_info:
            await FileService.upload(file=file, user_id="user-abc")
        assert exc_info.value.status_code == 400

    async def test_missing_content_type_raises_400(self):
        file = _upload_file_mock(content_type=None)

        with pytest.raises(HTTPException) as exc_info:
            await FileService.upload(file=file, user_id="user-abc")
        assert exc_info.value.status_code == 400
        assert "Content type is required" in exc_info.value.detail

    async def test_empty_content_type_raises_400(self):
        file = _upload_file_mock(content_type="")

        with pytest.raises(HTTPException) as exc_info:
            await FileService.upload(file=file, user_id="user-abc")
        assert exc_info.value.status_code == 400

    async def test_unsupported_content_type_raises_415(self):
        file = _upload_file_mock(content_type="application/x-msdownload")

        with pytest.raises(HTTPException) as exc_info:
            await FileService.upload(file=file, user_id="user-abc")
        assert exc_info.value.status_code == 415

    async def test_file_too_large_raises_413(self):
        file = _upload_file_mock(filename="huge.pdf", content=_pdf_bytes(MAX_UPLOAD_BYTES + 1))

        with pytest.raises(HTTPException) as exc_info:
            await FileService.upload(file=file, user_id="user-abc")
        assert exc_info.value.status_code == 413
        assert "10 MB" in exc_info.value.detail

    async def test_content_length_preflight_raises_413(self):
        """Oversize Content-Length is rejected before reading any bytes."""
        file = _upload_file_mock(filename="huge.pdf")

        with pytest.raises(HTTPException) as exc_info:
            await FileService.upload(
                file=file, user_id="user-abc", content_length=MAX_UPLOAD_BYTES + 1
            )
        assert exc_info.value.status_code == 413
        file.read.assert_not_awaited()

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_file_exactly_10mb_succeeds(
        self,
        mock_del_cache,
        mock_files_collection,
        mock_cloudinary_upload,
        mock_chroma_client,
    ):
        """File at exactly the size boundary should pass the size check."""
        mock_cloudinary_upload.return_value = {
            "secure_url": "https://res.cloudinary.com/test/uploaded.pdf"
        }
        _successful_insert(mock_files_collection)
        file = _upload_file_mock(filename="big.pdf", content=_pdf_bytes(MAX_UPLOAD_BYTES))

        with _summary("summary"):
            result = await FileService.upload(file=file, user_id="user-abc")
        assert "file_id" in result

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_cloudinary_missing_secure_url_raises_500(
        self,
        mock_del_cache,
        mock_cloudinary_upload,
    ):
        mock_cloudinary_upload.return_value = {}  # No secure_url

        with _summary("summary"):
            with pytest.raises(HTTPException) as exc_info:
                await FileService.upload(file=_upload_file_mock(), user_id="user-abc")
            assert exc_info.value.status_code == 500
            assert "Invalid response" in exc_info.value.detail

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_cloudinary_exception_raises_500(
        self,
        mock_del_cache,
        mock_cloudinary_upload,
    ):
        mock_cloudinary_upload.side_effect = Exception("Cloudinary connection error")

        with _summary("summary"):
            with pytest.raises(HTTPException) as exc_info:
                await FileService.upload(file=_upload_file_mock(), user_id="user-abc")
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

        with _summary("summary"):
            with pytest.raises(HTTPException) as exc_info:
                await FileService.upload(file=_upload_file_mock(), user_id="user-abc")
            assert exc_info.value.status_code == 500
            assert "Failed to store file metadata" in exc_info.value.detail

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_success_without_conversation_id_skips_mirror(
        self,
        mock_del_cache,
        mock_files_collection,
        mock_cloudinary_upload,
        mock_chroma_client,
        mock_sandbox_mirror,
    ):
        mock_cloudinary_upload.return_value = {
            "secure_url": "https://res.cloudinary.com/test/uploaded.pdf"
        }
        _successful_insert(mock_files_collection)
        mock_mirror, mock_sidecar = mock_sandbox_mirror

        with _summary("This is a summary"):
            result = await FileService.upload(
                file=_upload_file_mock(),
                user_id="user-abc",
                conversation_id=None,
            )

        assert result["filename"] == "report.pdf"
        assert result["sandbox_path"] is None
        assert "file_id" in result
        mock_mirror.assert_not_awaited()
        mock_sidecar.assert_not_awaited()

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
        _successful_insert(mock_files_collection)
        file = _upload_file_mock(filename="multipage.pdf")

        with _summary(sample_document_summary_list):
            result = await FileService.upload(file=file, user_id="user-abc")

        assert "Summary of page 1" in result["description"]
        assert "Summary of page 2" in result["description"]


# ---------------------------------------------------------------------------
# process_summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessSummary:
    def test_string_input(self):
        description, page_wise = process_summary("Simple text summary")
        assert description == "Simple text summary"
        assert page_wise is None

    def test_list_input(self, sample_document_summary_list):
        description, page_wise = process_summary(sample_document_summary_list)
        assert "Summary of page 1" in description
        assert "Summary of page 2" in description
        assert isinstance(page_wise, list)
        assert len(page_wise) == 2
        assert page_wise[0]["summary"] == "Summary of page 1. "
        assert page_wise[0]["data"]["page_number"] == 1

    def test_document_summary_model_input(self, sample_document_summary_model):
        description, page_wise = process_summary(sample_document_summary_model)
        assert description == "Summary of page 1"
        assert isinstance(page_wise, dict)
        assert page_wise["summary"] == "Summary of page 1"
        assert page_wise["data"]["page_number"] == 1

    def test_invalid_type_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            process_summary(12345)
        assert exc_info.value.status_code == 400
        assert "Invalid file description format" in exc_info.value.detail

    def test_none_input_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            process_summary(None)
        assert exc_info.value.status_code == 400

    def test_dict_input_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            process_summary({"summary": "test"})
        assert exc_info.value.status_code == 400

    def test_empty_string_input(self):
        description, page_wise = process_summary("")
        assert description == ""
        assert page_wise is None

    def test_empty_list_input(self):
        description, page_wise = process_summary([])
        assert description == ""
        assert isinstance(page_wise, list)
        assert len(page_wise) == 0


# ---------------------------------------------------------------------------
# insert_metadata
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInsertMetadata:
    async def test_success(self, mock_files_collection):
        _successful_insert(mock_files_collection)

        await insert_metadata({"file_id": "f-1", "filename": "test.pdf"})

        mock_files_collection.insert_one.assert_awaited_once_with(
            document={"file_id": "f-1", "filename": "test.pdf"}
        )

    async def test_insertion_fails_raises_500(self, mock_files_collection):
        mock_result = MagicMock()
        mock_result.inserted_id = None
        mock_files_collection.insert_one = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await insert_metadata({"file_id": "f-1"})
        assert exc_info.value.status_code == 500
        assert "Failed to store file metadata" in exc_info.value.detail

    async def test_exception_propagates(self, mock_files_collection):
        mock_files_collection.insert_one = AsyncMock(side_effect=Exception("Connection lost"))

        with pytest.raises(Exception, match="Connection lost"):
            await insert_metadata({"file_id": "f-1"})


# ---------------------------------------------------------------------------
# index_file
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIndexFile:
    async def test_list_summary_multi_page(self, mock_chroma_client, sample_document_summary_list):
        _, mock_chroma_col = mock_chroma_client

        await index_file(
            file_id="f-1",
            user_id="user-abc",
            filename="doc.pdf",
            content_type="application/pdf",
            summary=sample_document_summary_list,
            conversation_id="conv-1",
        )

        mock_chroma_col.aadd_documents.assert_awaited_once()
        call_kwargs = mock_chroma_col.aadd_documents.call_args.kwargs
        documents = call_kwargs["documents"]
        ids = call_kwargs["ids"]
        assert len(documents) == 2
        assert len(ids) == 2
        assert documents[0].page_content == "Summary of page 1. "
        assert documents[0].metadata["page_number"] == 1
        assert documents[0].metadata["conversation_id"] == "conv-1"
        assert documents[1].page_content == "Summary of page 2. "
        assert documents[1].metadata["page_number"] == 2

    async def test_string_summary(self, mock_chroma_client):
        _, mock_chroma_col = mock_chroma_client

        await index_file(
            file_id="f-1",
            user_id="user-abc",
            filename="doc.txt",
            content_type="text/plain",
            summary="A plain text description",
        )

        mock_chroma_col.aadd_documents.assert_awaited_once()
        call_kwargs = mock_chroma_col.aadd_documents.call_args.kwargs
        documents = call_kwargs["documents"]
        assert len(documents) == 1
        assert documents[0].page_content == "A plain text description"
        assert call_kwargs["ids"] == ["f-1"]
        # No conversation_id when not provided
        assert "conversation_id" not in documents[0].metadata

    async def test_document_summary_model(self, mock_chroma_client, sample_document_summary_model):
        _, mock_chroma_col = mock_chroma_client

        await index_file(
            file_id="f-1",
            user_id="user-abc",
            filename="doc.pdf",
            content_type="application/pdf",
            summary=sample_document_summary_model,
        )

        mock_chroma_col.aadd_documents.assert_awaited_once()
        call_kwargs = mock_chroma_col.aadd_documents.call_args.kwargs
        documents = call_kwargs["documents"]
        assert len(documents) == 1
        assert documents[0].page_content == "Summary of page 1"

    async def test_chromadb_fails_logged_not_raised(self, mock_chroma_client):
        _, mock_chroma_col = mock_chroma_client
        mock_chroma_col.aadd_documents = AsyncMock(side_effect=Exception("ChromaDB down"))

        # Should not raise
        await index_file(
            file_id="f-1",
            user_id="user-abc",
            filename="doc.pdf",
            content_type="application/pdf",
            summary="summary",
        )

    async def test_chromadb_client_init_fails_logged_not_raised(self):
        with patch(
            "app.services.files.store.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            side_effect=Exception("ChromaDB init failed"),
        ):
            # Should not raise
            await index_file(
                file_id="f-1",
                user_id="user-abc",
                filename="doc.pdf",
                content_type="application/pdf",
                summary="summary",
            )

    async def test_list_summary_without_conversation_id(
        self, mock_chroma_client, sample_document_summary_list
    ):
        _, mock_chroma_col = mock_chroma_client

        await index_file(
            file_id="f-1",
            user_id="user-abc",
            filename="doc.pdf",
            content_type="application/pdf",
            summary=sample_document_summary_list,
            conversation_id=None,
        )

        documents = mock_chroma_col.aadd_documents.call_args.kwargs["documents"]
        for doc in documents:
            assert "conversation_id" not in doc.metadata

    async def test_string_summary_with_conversation_id(self, mock_chroma_client):
        _, mock_chroma_col = mock_chroma_client

        await index_file(
            file_id="f-1",
            user_id="user-abc",
            filename="doc.txt",
            content_type="text/plain",
            summary="A description",
            conversation_id="conv-99",
        )

        documents = mock_chroma_col.aadd_documents.call_args.kwargs["documents"]
        assert documents[0].metadata["conversation_id"] == "conv-99"


# ---------------------------------------------------------------------------
# reindex_file
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReindexFile:
    async def test_delete_then_index_success(self, mock_chroma_client):
        _, mock_chroma_col = mock_chroma_client

        await reindex_file(
            file_id="f-1",
            user_id="user-abc",
            filename="doc.pdf",
            content_type="application/pdf",
            summary="updated summary",
            conversation_id="conv-1",
        )

        mock_chroma_col.adelete.assert_awaited_once_with(ids=["f-1"])
        mock_chroma_col.aadd_documents.assert_awaited_once()
        call_kwargs = mock_chroma_col.aadd_documents.call_args.kwargs
        assert call_kwargs["ids"] == ["f-1"]
        assert call_kwargs["documents"][0].page_content == "updated summary"
        assert call_kwargs["documents"][0].metadata["conversation_id"] == "conv-1"

    async def test_delete_fails_continues_to_index(self, mock_chroma_client):
        _, mock_chroma_col = mock_chroma_client
        mock_chroma_col.adelete = AsyncMock(side_effect=Exception("Delete error"))

        await reindex_file(
            file_id="f-1",
            user_id="user-abc",
            filename="doc.pdf",
            content_type="application/pdf",
            summary="updated summary",
        )

        # Indexing still runs even though the delete failed
        mock_chroma_col.aadd_documents.assert_awaited_once()

    async def test_index_fails_logged_not_raised(self, mock_chroma_client):
        _, mock_chroma_col = mock_chroma_client
        mock_chroma_col.aadd_documents = AsyncMock(side_effect=Exception("Store error"))

        # Should not raise
        await reindex_file(
            file_id="f-1",
            user_id="user-abc",
            filename="doc.pdf",
            content_type="application/pdf",
            summary="updated summary",
        )

    async def test_chroma_client_init_fails_still_calls_index(self):
        """When the client is unavailable, delete_from_index swallows its error
        and index_file is still attempted."""
        with (
            patch(
                "app.services.files.store.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                side_effect=Exception("ChromaDB unavailable"),
            ),
            patch(
                "app.services.files.store.index_file",
                new_callable=AsyncMock,
            ) as mock_index,
        ):
            await reindex_file(
                file_id="f-1",
                user_id="user-abc",
                filename="doc.pdf",
                content_type="application/pdf",
                summary="summary",
            )
            mock_index.assert_awaited_once()


# ---------------------------------------------------------------------------
# FileService.delete
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFileServiceDelete:
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

        result = await FileService.delete(file_id="f-1", user_id="user-abc")

        assert result["message"] == "File deleted successfully"
        assert result["file_id"] == "f-1"
        assert result["filename"] == "doc.pdf"
        mock_files_collection.delete_one.assert_awaited_once()
        mock_cloudinary_destroy.assert_called_once_with("file_f-1_doc.pdf")
        mock_chroma_col.adelete.assert_awaited_once_with(ids=["f-1"])

    async def test_user_id_none_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            await FileService.delete(file_id="f-1", user_id=None)
        assert exc_info.value.status_code == 400
        assert "User ID is required" in exc_info.value.detail

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_file_not_found_raises_404(self, mock_del_cache, mock_files_collection):
        mock_files_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await FileService.delete(file_id="f-nonexistent", user_id="user-abc")
        assert exc_info.value.status_code == 404

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_mongo_delete_count_zero_raises_404(self, mock_del_cache, mock_files_collection):
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
            await FileService.delete(file_id="f-1", user_id="user-abc")
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

        # Should NOT raise
        result = await FileService.delete(file_id="f-1", user_id="user-abc")
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

        result = await FileService.delete(file_id="f-1", user_id="user-abc")
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

        result = await FileService.delete(file_id="f-1", user_id="user-abc")
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

        result = await FileService.delete(file_id="f-1", user_id="user-abc")
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

        result = await FileService.delete(file_id="f-1", user_id="user-abc")
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

        result = await FileService.delete(file_id="f-1", user_id="user-abc")
        assert result["filename"] == "Unknown"


# ---------------------------------------------------------------------------
# FileService.update
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFileServiceUpdate:
    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_file_not_found_raises_404(self, mock_del_cache, mock_files_collection):
        mock_files_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await FileService.update(
                file_id="f-missing",
                user_id="user-abc",
                update_data={"filename": "new.pdf"},
            )
        assert exc_info.value.status_code == 404

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_success_without_file_content(self, mock_del_cache, mock_files_collection):
        original_file = {
            "_id": ObjectId(),
            "file_id": "f-1",
            "user_id": "user-abc",
            "filename": "old.pdf",
            "type": "application/pdf",
            "description": "Old description",
            "created_at": datetime(2025, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2025, 1, 1, tzinfo=UTC),
        }
        updated_file = {
            **original_file,
            "filename": "new.pdf",
            "updated_at": datetime(2025, 6, 1, tzinfo=UTC),
        }

        mock_files_collection.find_one = AsyncMock(side_effect=[original_file, updated_file])
        mock_update_result = MagicMock()
        mock_update_result.modified_count = 1
        mock_files_collection.update_one = AsyncMock(return_value=mock_update_result)

        result = await FileService.update(
            file_id="f-1",
            user_id="user-abc",
            update_data={"filename": "new.pdf"},
        )

        assert result["filename"] == "new.pdf"
        mock_files_collection.update_one.assert_awaited_once()

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_with_file_content_regenerates_description(
        self, mock_del_cache, mock_files_collection
    ):
        original_file = {
            "_id": ObjectId(),
            "file_id": "f-1",
            "user_id": "user-abc",
            "filename": "doc.pdf",
            "type": "application/pdf",
            "description": "Old description",
            "conversation_id": "conv-1",
            "created_at": datetime(2025, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2025, 1, 1, tzinfo=UTC),
        }
        updated_file = {
            **original_file,
            "description": "New summary from content",
        }

        mock_files_collection.find_one = AsyncMock(side_effect=[original_file, updated_file])
        mock_update_result = MagicMock()
        mock_update_result.modified_count = 1
        mock_files_collection.update_one = AsyncMock(return_value=mock_update_result)

        with (
            _summary("New summary from content"),
            patch(
                "app.services.files.service.reindex_file",
                new_callable=AsyncMock,
            ) as mock_reindex,
        ):
            result = await FileService.update(
                file_id="f-1",
                user_id="user-abc",
                update_data={},
                file_content=b"new file bytes",
                conversation_id="conv-1",
            )

        assert result["description"] == "New summary from content"
        mock_reindex.assert_awaited_once()

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
            "app.services.files.service.generate_file_summary",
            new_callable=AsyncMock,
            side_effect=Exception("LLM unavailable"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await FileService.update(
                    file_id="f-1",
                    user_id="user-abc",
                    update_data={},
                    file_content=b"content",
                )
            assert exc_info.value.status_code == 500
            assert "Failed to process file" in exc_info.value.detail

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_chromadb_reindex_fails_continues(self, mock_del_cache, mock_files_collection):
        original_file = {
            "_id": ObjectId(),
            "file_id": "f-1",
            "user_id": "user-abc",
            "filename": "doc.pdf",
            "type": "application/pdf",
            "description": "old",
            "created_at": datetime(2025, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2025, 1, 1, tzinfo=UTC),
        }
        updated_file = {**original_file, "description": "new desc"}

        mock_files_collection.find_one = AsyncMock(side_effect=[original_file, updated_file])
        mock_update_result = MagicMock()
        mock_update_result.modified_count = 1
        mock_files_collection.update_one = AsyncMock(return_value=mock_update_result)

        with patch(
            "app.services.files.store.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            side_effect=Exception("ChromaDB down"),
        ):
            # Should NOT raise — the vector index is best-effort
            result = await FileService.update(
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
            await FileService.update(
                file_id="f-1",
                user_id="user-abc",
                update_data={"filename": "new.pdf"},
            )
        assert exc_info.value.status_code == 404
        assert "not found after update" in exc_info.value.detail

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_no_conversation_id_uses_existing(self, mock_del_cache, mock_files_collection):
        original_file = {
            "_id": ObjectId(),
            "file_id": "f-1",
            "user_id": "user-abc",
            "filename": "doc.pdf",
            "type": "application/pdf",
            "conversation_id": "conv-existing",
            "description": "desc",
            "created_at": datetime(2025, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2025, 1, 1, tzinfo=UTC),
        }
        updated_file = {**original_file, "description": "updated desc"}

        mock_files_collection.find_one = AsyncMock(side_effect=[original_file, updated_file])
        mock_update_result = MagicMock()
        mock_update_result.modified_count = 1
        mock_files_collection.update_one = AsyncMock(return_value=mock_update_result)

        with patch(
            "app.services.files.service.reindex_file",
            new_callable=AsyncMock,
        ) as mock_reindex:
            await FileService.update(
                file_id="f-1",
                user_id="user-abc",
                update_data={"description": "updated desc"},
                conversation_id=None,
            )

        # Verify the reindex was scoped to the file's existing conversation
        mock_reindex.assert_awaited_once()
        call_kwargs = mock_reindex.call_args.kwargs
        assert call_kwargs["conversation_id"] == "conv-existing"

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_modified_count_zero_still_returns(self, mock_del_cache, mock_files_collection):
        original_file = {
            "_id": ObjectId(),
            "file_id": "f-1",
            "user_id": "user-abc",
            "filename": "doc.pdf",
            "type": "application/pdf",
            "created_at": datetime(2025, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2025, 1, 1, tzinfo=UTC),
        }

        mock_files_collection.find_one = AsyncMock(side_effect=[original_file, original_file])
        mock_update_result = MagicMock()
        mock_update_result.modified_count = 0  # no changes
        mock_files_collection.update_one = AsyncMock(return_value=mock_update_result)

        result = await FileService.update(
            file_id="f-1",
            user_id="user-abc",
            update_data={"filename": "doc.pdf"},  # same name
        )
        assert result is not None

    @patch(PATCH_DELETE_CACHE, new_callable=AsyncMock)
    async def test_description_not_updated_skips_reindex(
        self, mock_del_cache, mock_files_collection
    ):
        """When description is not in update_data, the vector index is untouched."""
        original_file = {
            "_id": ObjectId(),
            "file_id": "f-1",
            "user_id": "user-abc",
            "filename": "doc.pdf",
            "type": "application/pdf",
            "created_at": datetime(2025, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2025, 1, 1, tzinfo=UTC),
        }
        updated_file = {**original_file, "filename": "renamed.pdf"}

        mock_files_collection.find_one = AsyncMock(side_effect=[original_file, updated_file])
        mock_update_result = MagicMock()
        mock_update_result.modified_count = 1
        mock_files_collection.update_one = AsyncMock(return_value=mock_update_result)

        with patch(
            "app.services.files.service.reindex_file",
            new_callable=AsyncMock,
        ) as mock_reindex:
            await FileService.update(
                file_id="f-1",
                user_id="user-abc",
                update_data={"filename": "renamed.pdf"},
            )

        mock_reindex.assert_not_awaited()
