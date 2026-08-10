"""Unit tests for the support service (app/services/support_service.py)."""

from datetime import UTC, datetime
import re
import threading
from unittest.mock import AsyncMock, MagicMock, call, patch
import uuid

from fastapi import HTTPException, UploadFile
import pytest

from app.models.support_models import (
    SupportEmailNotification,
    SupportRequestCreate,
    SupportRequestDocument,
    SupportRequestPriority,
    SupportRequestResponse,
    SupportRequestStatus,
    SupportRequestSubmissionResponse,
    SupportRequestType,
)
from app.services.support_service import (
    SUPPORT_EMAILS,
    _delete_uploaded_files,
    _send_support_email_notifications,
    _upload_single_attachment,
    create_support_request,
    create_support_request_with_attachments,
    get_user_support_requests,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

USER_ID = "user_test_123"
USER_EMAIL = "testuser@example.com"
USER_NAME = "Test User"
TICKET_ID = "GAIA-20260320-ABCD1234"
REQUEST_ID = "req-uuid-1234"

ALLOWED_TYPES = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_support_repo():
    """Patch the support-requests repository seam.

    ``create`` echoes the document back with ``updated_at`` stamped (as the real
    base does on insert); ``delete`` reports a successful rollback by default.
    """
    repo = AsyncMock()

    async def _create(doc: SupportRequestDocument) -> SupportRequestDocument:
        if doc.updated_at is None:
            doc.updated_at = datetime.now(UTC)
        return doc

    repo.create.side_effect = _create
    repo.delete.return_value = True
    with patch("app.services.support_service.support_request_repository", repo):
        yield repo


@pytest.fixture
def mock_cloudinary():
    with patch("app.services.support_service.cloudinary.uploader") as mock_uploader:
        yield mock_uploader


@pytest.fixture
def mock_upload_file_to_cloudinary():
    with patch("app.services.support_service.upload_file_to_cloudinary") as mock_upload:
        mock_upload.return_value = "https://res.cloudinary.com/demo/support/ticket_file.png"
        yield mock_upload


@pytest.fixture
def mock_send_team_notification():
    with patch(
        "app.services.support_service.send_support_team_notification",
        new_callable=AsyncMock,
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_send_user_email():
    with patch(
        "app.services.support_service.send_support_to_user_email",
        new_callable=AsyncMock,
    ) as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_email_notifications(mock_send_team_notification, mock_send_user_email):
    """Convenience fixture that patches both email functions."""
    return mock_send_team_notification, mock_send_user_email


@pytest.fixture
def sample_request_data():
    return SupportRequestCreate(
        type=SupportRequestType.SUPPORT,
        title="Test Support Request",
        description="This is a test support request with enough characters.",
    )


@pytest.fixture
def sample_feature_request_data():
    return SupportRequestCreate(
        type=SupportRequestType.FEATURE,
        title="Feature Request",
        description="I would like a feature that does something useful.",
    )


def _make_upload_file(
    filename: str = "test.png",
    content_type: str = "image/png",
    content: bytes = b"fake-image-data",
) -> UploadFile:
    """Create a mock UploadFile with controllable attributes."""
    upload = MagicMock(spec=UploadFile)
    upload.filename = filename
    upload.content_type = content_type
    upload.read = AsyncMock(return_value=content)
    return upload


def _make_support_doc(
    request_id: str = REQUEST_ID,
    ticket_id: str = TICKET_ID,
    req_type: SupportRequestType = SupportRequestType.SUPPORT,
) -> SupportRequestDocument:
    """A support request document as the repository returns it."""
    now = datetime.now(UTC)
    return SupportRequestDocument(
        id=request_id,
        ticket_id=ticket_id,
        user_id=USER_ID,
        user_email=USER_EMAIL,
        user_name=USER_NAME,
        type=req_type,
        title="Test Request",
        description="A test support request with enough characters.",
        created_at=now,
        updated_at=now,
    )


# ===========================================================================
# _delete_uploaded_files
# ===========================================================================


class TestDeleteUploadedFiles:
    async def test_success_deletion(self, mock_cloudinary):
        """Cloudinary destroy is called and succeeds for a well-formed URL."""
        mock_cloudinary.destroy.return_value = {"result": "ok"}

        urls = ["https://res.cloudinary.com/demo/image/upload/support/TICKET_file.png"]
        await _delete_uploaded_files(urls)

        mock_cloudinary.destroy.assert_called_once_with("support/TICKET_file")

    async def test_success_logs_info_with_exact_public_id(self, mock_cloudinary):
        """A successful deletion logs info with the exact public id."""
        mock_cloudinary.destroy.return_value = {"result": "ok"}

        urls = ["https://res.cloudinary.com/demo/image/upload/support/TICKET_file.png"]
        with patch("app.services.support_service.log") as mock_log:
            await _delete_uploaded_files(urls)

        mock_log.info.assert_called_once_with(
            "Successfully deleted file from Cloudinary", public_id="support/TICKET_file"
        )

    async def test_warning_logs_exact_public_id(self, mock_cloudinary):
        """A non-ok result logs a warning carrying the exact public id."""
        mock_cloudinary.destroy.return_value = {"result": "not found"}

        urls = ["https://res.cloudinary.com/demo/image/upload/support/TICKET_file.png"]
        with patch("app.services.support_service.log") as mock_log:
            await _delete_uploaded_files(urls)

        mock_log.warning.assert_called_once_with(
            "Failed to delete file from Cloudinary", public_id="support/TICKET_file"
        )

    async def test_filename_without_extension_keeps_public_id(self, mock_cloudinary):
        """A filename with no extension is used verbatim as the public id."""
        mock_cloudinary.destroy.return_value = {"result": "ok"}

        urls = ["https://res.cloudinary.com/demo/image/upload/support/TICKET_file"]
        await _delete_uploaded_files(urls)

        mock_cloudinary.destroy.assert_called_once_with("support/TICKET_file")

    async def test_multi_underscore_filename_uses_first_segment(self, mock_cloudinary):
        """ticket_id is the segment before the FIRST underscore; public_id keeps the full name."""
        mock_cloudinary.destroy.side_effect = Exception("boom")

        urls = ["https://res.cloudinary.com/demo/image/upload/support/TICKET_photo_v2.png"]
        with patch("app.services.support_service.log") as mock_log:
            await _delete_uploaded_files(urls)

        mock_cloudinary.destroy.assert_called_once_with("support/TICKET_photo_v2")
        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.kwargs["ticket_id"] == "TICKET"

    async def test_dotted_filename_strips_only_final_extension(self, mock_cloudinary):
        """Only the last extension is stripped from the public id."""
        mock_cloudinary.destroy.side_effect = Exception("boom")

        urls = ["https://res.cloudinary.com/demo/image/upload/support/TICKET_file.tar.gz"]
        with patch("app.services.support_service.log") as mock_log:
            await _delete_uploaded_files(urls)

        mock_cloudinary.destroy.assert_called_once_with("support/TICKET_file.tar")
        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.kwargs["ticket_id"] == "TICKET"

    async def test_multiple_urls_mixed_outcomes_log_each(self, mock_cloudinary):
        """Each URL is logged individually: info on ok, warning on non-ok, error on exception."""
        mock_cloudinary.destroy.side_effect = [
            {"result": "ok"},
            Exception("boom"),
            {"result": "deleted"},
        ]

        urls = [
            "https://res.cloudinary.com/demo/image/upload/support/T1_a.png",
            "https://res.cloudinary.com/demo/image/upload/support/T2_b.png",
            "https://res.cloudinary.com/demo/image/upload/support/T3_c.png",
        ]
        with patch("app.services.support_service.log") as mock_log:
            await _delete_uploaded_files(urls)

        assert mock_log.info.call_count == 1
        assert mock_log.warning.call_count == 1
        mock_log.error.assert_called_once_with(
            "Error deleting file from Cloudinary",
            url=urls[1],
            ticket_id="T2",
            error="boom",
            error_type="Exception",
        )

    async def test_malformed_url_without_support_segment_is_skipped(self, mock_cloudinary):
        """URLs that do not contain 'support/' are silently skipped."""
        urls = ["https://example.com/other/path/file.png"]
        await _delete_uploaded_files(urls)

        mock_cloudinary.destroy.assert_not_called()

    async def test_support_segment_at_end_without_filename_is_skipped(self, mock_cloudinary):
        """URL where 'support' is the last segment (no filename after it) is skipped."""
        urls = ["https://res.cloudinary.com/demo/image/upload/support"]
        await _delete_uploaded_files(urls)

        mock_cloudinary.destroy.assert_not_called()

    async def test_cloudinary_result_not_ok_logs_warning(self, mock_cloudinary):
        """When Cloudinary returns a result other than 'ok', a warning is logged."""
        mock_cloudinary.destroy.return_value = {"result": "not found"}

        urls = ["https://res.cloudinary.com/demo/image/upload/support/TICKET_file.png"]
        with patch("app.services.support_service.log") as mock_log:
            await _delete_uploaded_files(urls)

            mock_log.warning.assert_called_once()
            assert "Failed to delete" in mock_log.warning.call_args[0][0]

    async def test_exception_during_destroy_is_logged(self, mock_cloudinary):
        """Exceptions from Cloudinary are caught and logged, not re-raised."""
        mock_cloudinary.destroy.side_effect = Exception("network error")

        urls = ["https://res.cloudinary.com/demo/image/upload/support/TICKET_file.png"]
        with patch("app.services.support_service.log") as mock_log:
            await _delete_uploaded_files(urls)

            mock_log.error.assert_called_once()
            assert mock_log.error.call_args.kwargs["error"] == "network error"
            assert mock_log.error.call_args.kwargs["ticket_id"] == "TICKET"

    async def test_multiple_urls_processed_independently(self, mock_cloudinary):
        """All URLs are processed even if one fails."""
        mock_cloudinary.destroy.side_effect = [
            {"result": "ok"},
            Exception("fail"),
            {"result": "ok"},
        ]

        urls = [
            "https://res.cloudinary.com/demo/image/upload/support/TICKET_a.png",
            "https://res.cloudinary.com/demo/image/upload/support/TICKET_b.png",
            "https://res.cloudinary.com/demo/image/upload/support/TICKET_c.png",
        ]
        with patch("app.services.support_service.log"):
            await _delete_uploaded_files(urls)

        assert mock_cloudinary.destroy.call_count == 3

    async def test_empty_url_list_does_nothing(self, mock_cloudinary):
        """An empty URL list results in no Cloudinary calls."""
        await _delete_uploaded_files([])
        mock_cloudinary.destroy.assert_not_called()

    async def test_destroy_runs_off_the_event_loop(self, mock_cloudinary):
        """Cloudinary's SDK is blocking HTTP. Called inline from a coroutine it
        stalls the whole worker for the length of the round trip — every other
        request on that process waits behind a support-ticket cleanup."""
        loop_thread = threading.current_thread()
        call_threads: list[threading.Thread] = []

        def record_calling_thread(public_id: str) -> dict[str, str]:
            call_threads.append(threading.current_thread())
            return {"result": "ok"}

        mock_cloudinary.destroy.side_effect = record_calling_thread

        urls = ["https://res.cloudinary.com/demo/image/upload/support/TICKET_file.png"]
        await _delete_uploaded_files(urls)

        assert call_threads, "destroy was never called"
        assert call_threads[0] is not loop_thread


# ===========================================================================
# _upload_single_attachment
# ===========================================================================


class TestUploadSingleAttachment:
    async def test_success_upload(self, mock_upload_file_to_cloudinary):
        """Happy path: valid file is uploaded and metadata is returned."""
        upload = _make_upload_file(
            filename="screenshot.png",
            content_type="image/png",
            content=b"x" * 100,
        )
        current_time = datetime.now(UTC)

        file_url, attachment_meta = await _upload_single_attachment(
            attachment=upload,
            ticket_id="T1",
            current_time=current_time,
            allowed_types=ALLOWED_TYPES,
            max_file_size=MAX_FILE_SIZE,
        )

        assert file_url == mock_upload_file_to_cloudinary.return_value
        assert attachment_meta.filename == "screenshot.png"
        assert attachment_meta.file_size == 100
        assert attachment_meta.content_type == "image/png"
        assert attachment_meta.file_url == file_url

    async def test_success_passes_exact_public_id_and_content(self, mock_upload_file_to_cloudinary):
        """The upload seam receives the exact public_id and raw file content."""
        content = b"payload-bytes"
        upload = _make_upload_file(
            filename="screenshot.png",
            content_type="image/png",
            content=content,
        )
        current_time = datetime.now(UTC)

        await _upload_single_attachment(
            attachment=upload,
            ticket_id="T1",
            current_time=current_time,
            allowed_types=ALLOWED_TYPES,
            max_file_size=MAX_FILE_SIZE,
        )

        mock_upload_file_to_cloudinary.assert_called_once_with(
            public_id="support/T1_screenshot.png",
            file_data=content,
        )

    async def test_success_metadata_exact(self, mock_upload_file_to_cloudinary):
        """Attachment metadata mirrors the uploaded file exactly."""
        content = b"x" * 42
        upload = _make_upload_file(
            filename="shot.png",
            content_type="image/png",
            content=content,
        )
        current_time = datetime.now(UTC)

        _, meta = await _upload_single_attachment(
            attachment=upload,
            ticket_id="T1",
            current_time=current_time,
            allowed_types=ALLOWED_TYPES,
            max_file_size=MAX_FILE_SIZE,
        )

        assert meta.filename == "shot.png"
        assert meta.file_size == 42
        assert meta.content_type == "image/png"
        assert meta.file_url == mock_upload_file_to_cloudinary.return_value
        assert meta.uploaded_at == current_time

    async def test_wrong_content_type_exact_detail(self):
        """The 400 detail names the rejected content type."""
        upload = _make_upload_file(
            filename="doc.pdf",
            content_type="application/pdf",
        )
        current_time = datetime.now(UTC)

        with pytest.raises(HTTPException) as exc_info:
            await _upload_single_attachment(
                attachment=upload,
                ticket_id="T1",
                current_time=current_time,
                allowed_types=ALLOWED_TYPES,
                max_file_size=MAX_FILE_SIZE,
            )

        assert exc_info.value.status_code == 400
        assert (
            exc_info.value.detail
            == "Only image files are supported. File type application/pdf not allowed. "
            "Please use JPG, PNG, or WebP."
        )

    async def test_missing_filename_exact_detail(self):
        """The 400 detail for a missing filename is exact."""
        upload = _make_upload_file(filename="", content_type="image/png")
        current_time = datetime.now(UTC)

        with pytest.raises(HTTPException) as exc_info:
            await _upload_single_attachment(
                attachment=upload,
                ticket_id="T1",
                current_time=current_time,
                allowed_types=ALLOWED_TYPES,
                max_file_size=MAX_FILE_SIZE,
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "All images must have filenames"

    async def test_file_too_large_exact_detail(self):
        """The 400 detail for an oversized file names the file and the 10MB cap."""
        oversized_content = b"x" * (MAX_FILE_SIZE + 1)
        upload = _make_upload_file(
            filename="big.png",
            content_type="image/png",
            content=oversized_content,
        )
        current_time = datetime.now(UTC)

        with pytest.raises(HTTPException) as exc_info:
            await _upload_single_attachment(
                attachment=upload,
                ticket_id="T1",
                current_time=current_time,
                allowed_types=ALLOWED_TYPES,
                max_file_size=MAX_FILE_SIZE,
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "File big.png exceeds maximum size of 10MB"

    async def test_wrong_content_type_raises_400(self):
        """Non-image content type raises 400."""
        upload = _make_upload_file(
            filename="doc.pdf",
            content_type="application/pdf",
        )
        current_time = datetime.now(UTC)

        with pytest.raises(HTTPException) as exc_info:
            await _upload_single_attachment(
                attachment=upload,
                ticket_id="T1",
                current_time=current_time,
                allowed_types=ALLOWED_TYPES,
                max_file_size=MAX_FILE_SIZE,
            )

        assert exc_info.value.status_code == 400
        assert "not allowed" in exc_info.value.detail

    async def test_missing_filename_raises_400(self):
        """Attachment without a filename raises 400."""
        upload = _make_upload_file(filename="", content_type="image/png")
        # UploadFile.filename being falsy (empty string) triggers the check
        upload.filename = ""
        current_time = datetime.now(UTC)

        with pytest.raises(HTTPException) as exc_info:
            await _upload_single_attachment(
                attachment=upload,
                ticket_id="T1",
                current_time=current_time,
                allowed_types=ALLOWED_TYPES,
                max_file_size=MAX_FILE_SIZE,
            )

        assert exc_info.value.status_code == 400
        assert "filenames" in exc_info.value.detail

    async def test_none_filename_raises_400(self):
        """Attachment with None filename raises 400."""
        upload = _make_upload_file(content_type="image/png")
        upload.filename = None
        current_time = datetime.now(UTC)

        with pytest.raises(HTTPException) as exc_info:
            await _upload_single_attachment(
                attachment=upload,
                ticket_id="T1",
                current_time=current_time,
                allowed_types=ALLOWED_TYPES,
                max_file_size=MAX_FILE_SIZE,
            )

        assert exc_info.value.status_code == 400

    async def test_file_too_large_raises_400(self):
        """File exceeding max size raises 400."""
        oversized_content = b"x" * (MAX_FILE_SIZE + 1)
        upload = _make_upload_file(
            filename="big.png",
            content_type="image/png",
            content=oversized_content,
        )
        current_time = datetime.now(UTC)

        with pytest.raises(HTTPException) as exc_info:
            await _upload_single_attachment(
                attachment=upload,
                ticket_id="T1",
                current_time=current_time,
                allowed_types=ALLOWED_TYPES,
                max_file_size=MAX_FILE_SIZE,
            )

        assert exc_info.value.status_code == 400
        assert "exceeds maximum size" in exc_info.value.detail

    async def test_file_exactly_at_max_size_succeeds(self, mock_upload_file_to_cloudinary):
        """File exactly at max size should succeed."""
        content = b"x" * MAX_FILE_SIZE
        upload = _make_upload_file(
            filename="exact.png",
            content_type="image/png",
            content=content,
        )
        current_time = datetime.now(UTC)

        file_url, _ = await _upload_single_attachment(
            attachment=upload,
            ticket_id="T1",
            current_time=current_time,
            allowed_types=ALLOWED_TYPES,
            max_file_size=MAX_FILE_SIZE,
        )

        assert file_url is not None

    async def test_upload_failure_raises_500(self):
        """Cloudinary upload failure raises 500."""
        upload = _make_upload_file(
            filename="fail.png",
            content_type="image/png",
            content=b"data",
        )
        current_time = datetime.now(UTC)

        with patch(
            "app.services.support_service.upload_file_to_cloudinary",
            side_effect=Exception("Cloudinary down"),
        ):
            with patch("app.services.support_service.log"):
                with pytest.raises(HTTPException) as exc_info:
                    await _upload_single_attachment(
                        attachment=upload,
                        ticket_id="T1",
                        current_time=current_time,
                        allowed_types=ALLOWED_TYPES,
                        max_file_size=MAX_FILE_SIZE,
                    )

        assert exc_info.value.status_code == 500
        assert "Failed to upload" in exc_info.value.detail

    async def test_upload_failure_logs_exact_error_and_detail(self):
        """Upload failure logs the exact error context and raises a 500 with the filename."""
        upload = _make_upload_file(
            filename="fail.png",
            content_type="image/png",
            content=b"data",
        )
        current_time = datetime.now(UTC)

        with patch(
            "app.services.support_service.upload_file_to_cloudinary",
            side_effect=RuntimeError("Cloudinary down"),
        ):
            with patch("app.services.support_service.log") as mock_log:
                with pytest.raises(HTTPException) as exc_info:
                    await _upload_single_attachment(
                        attachment=upload,
                        ticket_id="T1",
                        current_time=current_time,
                        allowed_types=ALLOWED_TYPES,
                        max_file_size=MAX_FILE_SIZE,
                    )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to upload image fail.png"
        mock_log.error.assert_called_once_with(
            "Failed to upload image",
            filename="fail.png",
            error="Cloudinary down",
            error_type="RuntimeError",
            ticket_id="T1",
        )

    async def test_all_allowed_types_accepted(self, mock_upload_file_to_cloudinary):
        """Each allowed content type can be uploaded."""
        for ctype in ALLOWED_TYPES:
            upload = _make_upload_file(
                filename=f"file.{ctype.split('/')[-1]}",
                content_type=ctype,
                content=b"data",
            )
            current_time = datetime.now(UTC)

            file_url, meta = await _upload_single_attachment(
                attachment=upload,
                ticket_id="T1",
                current_time=current_time,
                allowed_types=ALLOWED_TYPES,
                max_file_size=MAX_FILE_SIZE,
            )
            assert file_url is not None


# ===========================================================================
# create_support_request
# ===========================================================================


class TestCreateSupportRequest:
    async def test_success(
        self,
        mock_support_repo,
        mock_email_notifications,
        sample_request_data,
    ):
        """Happy path: repository stores the request, emails succeed, response returned."""
        with patch("app.services.support_service.log"):
            result = await create_support_request(
                request_data=sample_request_data,
                user_id=USER_ID,
                user_email=USER_EMAIL,
                user_name=USER_NAME,
            )

        assert isinstance(result, SupportRequestSubmissionResponse)
        assert result.success is True
        assert result.ticket_id is not None
        assert result.support_request is not None
        assert result.support_request.user_id == USER_ID
        assert result.support_request.status == SupportRequestStatus.OPEN
        assert result.support_request.priority == SupportRequestPriority.MEDIUM
        mock_support_repo.create.assert_awaited_once()

    async def test_success_stored_document_exact_fields(
        self,
        mock_support_repo,
        mock_email_notifications,
        sample_request_data,
    ):
        """The document persisted to the repository carries every field exactly."""
        with patch("app.services.support_service.log"):
            result = await create_support_request(
                request_data=sample_request_data,
                user_id=USER_ID,
                user_email=USER_EMAIL,
                user_name=USER_NAME,
            )

        stored = mock_support_repo.create.await_args.args[0]
        assert isinstance(stored, SupportRequestDocument)
        assert uuid.UUID(stored.id)
        assert stored.user_id == USER_ID
        assert stored.user_email == USER_EMAIL
        assert stored.user_name == USER_NAME
        assert stored.type is SupportRequestType.SUPPORT
        assert stored.title == "Test Support Request"
        assert stored.description == "This is a test support request with enough characters."
        assert stored.status is SupportRequestStatus.OPEN
        assert stored.priority is SupportRequestPriority.MEDIUM
        assert stored.attachments == []
        assert stored.metadata == {"source": "web_form", "user_agent": None}
        assert stored.created_at == result.support_request.created_at
        assert result.support_request.id == stored.id
        assert result.support_request.ticket_id == stored.ticket_id

    async def test_success_ticket_id_format(
        self,
        mock_support_repo,
        mock_email_notifications,
        sample_request_data,
    ):
        """Ticket ids follow GAIA-YYYYMMDD-XXXXXXXX."""
        with patch("app.services.support_service.log"):
            result = await create_support_request(
                request_data=sample_request_data,
                user_id=USER_ID,
                user_email=USER_EMAIL,
            )

        assert re.fullmatch(r"GAIA-\d{8}-[A-F0-9]{8}", result.ticket_id)

    async def test_email_notification_exact_data(
        self,
        mock_support_repo,
        mock_send_team_notification,
        mock_send_user_email,
        sample_request_data,
    ):
        """The email notification payload carries every field exactly."""
        with patch("app.services.support_service.log"):
            result = await create_support_request(
                request_data=sample_request_data,
                user_id=USER_ID,
                user_email=USER_EMAIL,
                user_name=USER_NAME,
            )

        notification = mock_send_team_notification.await_args.args[0]
        assert isinstance(notification, SupportEmailNotification)
        assert notification.user_name == USER_NAME
        assert notification.user_email == USER_EMAIL
        assert notification.ticket_id == result.ticket_id
        assert notification.type is SupportRequestType.SUPPORT
        assert notification.title == "Test Support Request"
        assert notification.description == "This is a test support request with enough characters."
        assert notification.support_emails == SUPPORT_EMAILS
        assert notification.attachments == []
        assert notification.created_at == result.support_request.created_at
        mock_send_user_email.assert_awaited_once_with(notification)

    async def test_success_exact_message(
        self,
        mock_support_repo,
        mock_email_notifications,
        sample_request_data,
    ):
        """The success message is the exact confirmation copy."""
        with patch("app.services.support_service.log"):
            result = await create_support_request(
                request_data=sample_request_data,
                user_id=USER_ID,
                user_email=USER_EMAIL,
            )

        assert (
            result.message
            == "Support request submitted successfully. You will receive an email confirmation shortly."
        )

    async def test_log_set_called_with_identity(
        self,
        mock_support_repo,
        mock_email_notifications,
        sample_request_data,
    ):
        """The wide-event context is set with the caller's identity."""
        with patch("app.services.support_service.log") as mock_log:
            await create_support_request(
                request_data=sample_request_data,
                user_id=USER_ID,
                user_email=USER_EMAIL,
            )

        mock_log.set.assert_called_once_with(
            component="support_service",
            user_id=USER_ID,
            user_email=USER_EMAIL,
        )

    async def test_email_failure_exact_detail_and_rollback(
        self,
        mock_support_repo,
        mock_send_team_notification,
        mock_send_user_email,
        sample_request_data,
    ):
        """Email failure raises the exact 500 detail and rolls back the created document."""
        mock_send_team_notification.side_effect = Exception("SMTP error")

        with patch("app.services.support_service.log") as mock_log:
            with pytest.raises(HTTPException) as exc_info:
                await create_support_request(
                    request_data=sample_request_data,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        assert exc_info.value.status_code == 500
        assert (
            exc_info.value.detail
            == "Failed to send email notifications. Support request was not created. Please try again."
        )
        created_id = mock_support_repo.create.await_args.args[0].id
        mock_support_repo.delete.assert_awaited_once_with(created_id, user_id=USER_ID)
        info_calls = [str(c) for c in mock_log.info.call_args_list]
        assert any("Successfully rolled back" in call for call in info_calls)

    async def test_email_failure_rollback_error_logged(
        self,
        mock_support_repo,
        mock_send_team_notification,
        mock_send_user_email,
        sample_request_data,
    ):
        """When the rollback delete itself fails, the rollback error is logged."""
        mock_support_repo.delete.side_effect = Exception("DB unreachable")
        mock_send_team_notification.side_effect = Exception("SMTP error")

        with patch("app.services.support_service.log") as mock_log:
            with pytest.raises(HTTPException):
                await create_support_request(
                    request_data=sample_request_data,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        error_calls = [str(c) for c in mock_log.error.call_args_list]
        assert any("Error during rollback for ticket" in call for call in error_calls)

    async def test_repository_http_exception_re_raised_without_rollback(
        self,
        mock_support_repo,
        sample_request_data,
    ):
        """An HTTPException from the repository passes through untouched, no rollback."""
        mock_support_repo.create.side_effect = HTTPException(status_code=422, detail="bad data")

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await create_support_request(
                    request_data=sample_request_data,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == "bad data"
        mock_support_repo.delete.assert_not_awaited()

    async def test_unexpected_error_before_request_id_no_rollback(
        self,
        mock_support_repo,
        sample_request_data,
    ):
        """Failure before any request id is minted cannot roll back and skips delete."""
        with patch(
            "app.services.support_service.uuid.uuid4",
            side_effect=RuntimeError("uuid boom"),
        ):
            with patch("app.services.support_service.log"):
                with pytest.raises(HTTPException) as exc_info:
                    await create_support_request(
                        request_data=sample_request_data,
                        user_id=USER_ID,
                        user_email=USER_EMAIL,
                    )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to create support request: uuid boom"
        mock_support_repo.delete.assert_not_awaited()

    async def test_success_logs_exact_sequence(
        self,
        mock_support_repo,
        mock_email_notifications,
        sample_request_data,
    ):
        """The success path logs the exact wide-event sequence with the real ticket id."""
        with patch("app.services.support_service.log") as mock_log:
            result = await create_support_request(
                request_data=sample_request_data,
                user_id=USER_ID,
                user_email=USER_EMAIL,
            )

        ticket_id = mock_support_repo.create.await_args.args[0].ticket_id
        mock_log.assert_has_calls(
            [
                call.set(component="support_service", user_id=USER_ID, user_email=USER_EMAIL),
                call.info("Support request created in database", ticket_id=ticket_id),
                call.info("Email notifications sent successfully for ticket", ticket_id=ticket_id),
                call.info(
                    "Support request created successfully: for user",
                    ticket_id=ticket_id,
                    user_id=USER_ID,
                ),
            ]
        )
        assert result.ticket_id == ticket_id

    async def test_created_at_is_the_utc_now_value(
        self,
        mock_support_repo,
        mock_email_notifications,
        sample_request_data,
    ):
        """The document's created_at is exactly datetime.now(UTC) at creation time."""
        fixed_now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        with patch("app.services.support_service.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            with patch("app.services.support_service.log"):
                result = await create_support_request(
                    request_data=sample_request_data,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        stored = mock_support_repo.create.await_args.args[0]
        assert stored.created_at == fixed_now
        assert result.support_request.created_at == fixed_now
        # The UTC tz argument is pinned: a naive now() would silently produce
        # an unaware created_at.
        mock_dt.now.assert_any_call(UTC)

    async def test_create_failure_rolls_back_and_raises_500(
        self,
        mock_support_repo,
        sample_request_data,
    ):
        """When the repository create fails, the request is rolled back and 500 raised."""
        mock_support_repo.create.side_effect = RuntimeError("write failed")

        with patch("app.services.support_service.log") as mock_log:
            with pytest.raises(HTTPException) as exc_info:
                await create_support_request(
                    request_data=sample_request_data,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to create support request: write failed"
        mock_support_repo.delete.assert_awaited_once()
        created_id = mock_support_repo.delete.await_args.args[0]
        mock_log.info.assert_called_once_with(
            "Rolled back support request due to unexpected error", request_id=created_id
        )
        mock_log.error.assert_called_once_with(
            "Unexpected error creating support request",
            error="write failed",
            error_type="RuntimeError",
            user_id=USER_ID,
        )

    async def test_email_failure_triggers_rollback_and_raises_500(
        self,
        mock_support_repo,
        mock_send_team_notification,
        mock_send_user_email,
        sample_request_data,
    ):
        """Email failure causes a repository delete (rollback) and raises 500."""
        mock_send_team_notification.side_effect = Exception("SMTP error")

        with patch("app.services.support_service.log") as mock_log:
            with pytest.raises(HTTPException) as exc_info:
                await create_support_request(
                    request_data=sample_request_data,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        assert exc_info.value.status_code == 500
        assert (
            exc_info.value.detail
            == "Failed to send email notifications. Support request was not created. Please try again."
        )
        created = mock_support_repo.create.await_args.args[0]
        mock_support_repo.delete.assert_awaited_once_with(created.id, user_id=USER_ID)
        ticket_id = created.ticket_id
        mock_log.error.assert_any_call(
            "Email sending failed for ticket",
            ticket_id=ticket_id,
            error="SMTP error",
            error_type="Exception",
            user_id=USER_ID,
        )
        mock_log.info.assert_has_calls(
            [
                call.info(
                    "Successfully rolled back support request from database", ticket_id=ticket_id
                )
            ]
        )

    async def test_email_failure_rollback_fails_still_raises_500(
        self,
        mock_support_repo,
        mock_send_team_notification,
        mock_send_user_email,
        sample_request_data,
    ):
        """Even if rollback itself fails, the 500 is still raised."""
        mock_support_repo.delete.side_effect = Exception("DB unreachable")
        mock_send_team_notification.side_effect = Exception("SMTP error")

        with patch("app.services.support_service.log") as mock_log:
            with pytest.raises(HTTPException) as exc_info:
                await create_support_request(
                    request_data=sample_request_data,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        assert exc_info.value.status_code == 500
        ticket_id = mock_support_repo.create.await_args.args[0].ticket_id
        mock_log.error.assert_any_call(
            "Error during rollback for ticket",
            ticket_id=ticket_id,
            error="DB unreachable",
            error_type="Exception",
            user_id=USER_ID,
        )

    async def test_email_failure_rollback_not_deleted_logs_error(
        self,
        mock_support_repo,
        mock_send_team_notification,
        mock_send_user_email,
        sample_request_data,
    ):
        """When rollback delete finds nothing to delete, an error is logged."""
        mock_support_repo.delete.return_value = False
        mock_send_team_notification.side_effect = Exception("SMTP error")

        with patch("app.services.support_service.log") as mock_log:
            with pytest.raises(HTTPException):
                await create_support_request(
                    request_data=sample_request_data,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

            ticket_id = mock_support_repo.create.await_args.args[0].ticket_id
            mock_log.error.assert_any_call(
                "Failed to rollback support request from database",
                ticket_id=ticket_id,
                error="SMTP error",
                error_type="Exception",
                user_id=USER_ID,
            )

    async def test_unexpected_error_with_rollback(
        self,
        mock_support_repo,
        sample_request_data,
    ):
        """Unexpected exception after request_id is set triggers rollback."""
        # Emails succeed, but response construction fails with a non-HTTP error.
        with patch(
            "app.services.support_service._send_support_email_notifications",
            new_callable=AsyncMock,
        ):
            with patch(
                "app.services.support_service.SupportRequestResponse.model_validate",
                side_effect=RuntimeError("unexpected"),
            ):
                with patch("app.services.support_service.log") as mock_log:
                    with pytest.raises(HTTPException) as exc_info:
                        await create_support_request(
                            request_data=sample_request_data,
                            user_id=USER_ID,
                            user_email=USER_EMAIL,
                        )

        assert exc_info.value.status_code == 500
        created_id = mock_support_repo.create.await_args.args[0].id
        mock_support_repo.delete.assert_awaited_once_with(created_id, user_id=USER_ID)
        mock_log.info.assert_any_call(
            "Rolled back support request due to unexpected error", request_id=created_id
        )
        mock_log.error.assert_called_once_with(
            "Unexpected error creating support request",
            error="unexpected",
            error_type="RuntimeError",
            user_id=USER_ID,
        )

    async def test_unexpected_error_rollback_failure_still_raises_500(
        self,
        mock_support_repo,
        sample_request_data,
    ):
        """When both the main operation and rollback fail, 500 is still raised."""
        mock_support_repo.delete.side_effect = Exception("rollback failed")

        with patch(
            "app.services.support_service._send_support_email_notifications",
            new_callable=AsyncMock,
        ):
            with patch(
                "app.services.support_service.SupportRequestResponse.model_validate",
                side_effect=RuntimeError("unexpected"),
            ):
                with patch("app.services.support_service.log") as mock_log:
                    with pytest.raises(HTTPException) as exc_info:
                        await create_support_request(
                            request_data=sample_request_data,
                            user_id=USER_ID,
                            user_email=USER_EMAIL,
                        )

        assert exc_info.value.status_code == 500
        created_id = mock_support_repo.create.await_args.args[0].id
        mock_log.error.assert_any_call(
            "Error during rollback for request",
            request_id=created_id,
            error="rollback failed",
            error_type="Exception",
            user_id=USER_ID,
        )
        mock_log.error.assert_any_call(
            "Unexpected error creating support request",
            error="unexpected",
            error_type="RuntimeError",
            user_id=USER_ID,
        )

    async def test_user_name_defaults_to_user_in_email(
        self,
        mock_support_repo,
        mock_send_team_notification,
        mock_send_user_email,
        sample_request_data,
    ):
        """When user_name is None, 'User' is used in email notifications."""
        with patch("app.services.support_service.log"):
            result = await create_support_request(
                request_data=sample_request_data,
                user_id=USER_ID,
                user_email=USER_EMAIL,
                user_name=None,
            )

        assert result.success is True
        notification = mock_send_team_notification.await_args.args[0]
        assert notification.user_name == "User"
        stored = mock_support_repo.create.await_args.args[0]
        assert stored.user_name is None


# ===========================================================================
# create_support_request_with_attachments
# ===========================================================================


class TestCreateSupportRequestWithAttachments:
    async def test_success_with_attachments(
        self,
        mock_support_repo,
        mock_email_notifications,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """Happy path: files uploaded, request stored, emails sent."""
        attachments = [
            _make_upload_file("img1.png", "image/png", b"data1"),
            _make_upload_file("img2.jpg", "image/jpeg", b"data2"),
        ]

        with patch("app.services.support_service.log") as mock_log:
            result = await create_support_request_with_attachments(
                request_data=sample_request_data,
                attachments=attachments,
                user_id=USER_ID,
                user_email=USER_EMAIL,
                user_name=USER_NAME,
            )

        assert isinstance(result, SupportRequestSubmissionResponse)
        assert result.success is True
        assert (
            result.message
            == "Support request with images submitted successfully. You will receive an email confirmation shortly."
        )
        assert result.ticket_id is not None
        mock_support_repo.create.assert_awaited_once()
        stored = mock_support_repo.create.await_args.args[0]
        assert len(stored.attachments) == 2  # both uploads recorded on the document
        ticket_id = stored.ticket_id
        mock_upload_file_to_cloudinary.assert_any_call(
            public_id=f"support/{ticket_id}_img1.png", file_data=b"data1"
        )
        mock_upload_file_to_cloudinary.assert_any_call(
            public_id=f"support/{ticket_id}_img2.jpg", file_data=b"data2"
        )
        mock_log.assert_has_calls(
            [
                call.set(
                    component="support_service",
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                    attachment_count=2,
                ),
                call.info(
                    "Successfully uploaded files in parallel for ticket",
                    attachment_urls_count=2,
                    ticket_id=ticket_id,
                ),
                call.info(
                    "Support request with attachments created in database", ticket_id=ticket_id
                ),
                call.info("Email notifications sent successfully for ticket", ticket_id=ticket_id),
                call.info(
                    "Support request with images created successfully: for user",
                    processed_attachments_count=2,
                    ticket_id=ticket_id,
                    user_id=USER_ID,
                ),
            ]
        )

    async def test_all_image_types_accepted_via_full_path(
        self,
        mock_support_repo,
        mock_email_notifications,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """image/jpg and image/webp files pass the whole request path."""
        attachments = [
            _make_upload_file("shot.jpg", "image/jpg", b"x" * 100),
            _make_upload_file("clip.webp", "image/webp", b"y" * 100),
        ]

        with patch("app.services.support_service.log"):
            result = await create_support_request_with_attachments(
                request_data=sample_request_data,
                attachments=attachments,
                user_id=USER_ID,
                user_email=USER_EMAIL,
            )

        assert result.success is True
        stored = mock_support_repo.create.await_args.args[0]
        assert [a.filename for a in stored.attachments] == ["shot.jpg", "clip.webp"]

    async def test_file_between_10mb_and_mutated_cap_still_rejected(
        self,
        mock_support_repo,
        mock_email_notifications,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """A file over 10MB is rejected even when a bumped cap would let it through."""
        over_10mb_but_under_1025kb_units = 10 * 1024 * 1024 + 100
        attachments = [
            _make_upload_file(
                "big.png", "image/png", content=b"x" * over_10mb_but_under_1025kb_units
            ),
        ]

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await create_support_request_with_attachments(
                    request_data=sample_request_data,
                    attachments=attachments,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        assert exc_info.value.status_code == 400
        assert "exceeds maximum size" in exc_info.value.detail
        mock_support_repo.create.assert_not_awaited()

    async def test_success_stored_document_exact_fields(
        self,
        mock_support_repo,
        mock_email_notifications,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """The persisted document carries exact attachment metadata and web-form-with-images source."""
        attachments = [
            _make_upload_file("img1.png", "image/png", b"data1"),
            _make_upload_file("img2.jpg", "image/jpeg", b"data2"),
        ]

        with patch("app.services.support_service.log"):
            result = await create_support_request_with_attachments(
                request_data=sample_request_data,
                attachments=attachments,
                user_id=USER_ID,
                user_email=USER_EMAIL,
                user_name=USER_NAME,
            )

        stored = mock_support_repo.create.await_args.args[0]
        assert isinstance(stored, SupportRequestDocument)
        assert stored.user_id == USER_ID
        assert stored.user_email == USER_EMAIL
        assert stored.user_name == USER_NAME
        assert stored.type is SupportRequestType.SUPPORT
        assert stored.priority is SupportRequestPriority.MEDIUM
        assert stored.ticket_id == result.ticket_id
        assert re.fullmatch(r"GAIA-\d{8}-[A-F0-9]{8}", stored.ticket_id)
        assert stored.metadata == {
            "source": "web_form_with_images",
            "user_agent": None,
            "image_count": 2,
        }
        assert len(stored.attachments) == 2
        assert stored.attachments[0].filename == "img1.png"
        assert stored.attachments[0].file_size == 5
        assert stored.attachments[0].content_type == "image/png"
        assert (
            stored.attachments[0].file_url
            == "https://res.cloudinary.com/demo/support/ticket_file.png"
        )
        assert stored.attachments[1].filename == "img2.jpg"
        assert stored.attachments[1].file_size == 5
        assert result.support_request.id == stored.id

    async def test_email_notification_carries_attachments(
        self,
        mock_support_repo,
        mock_send_team_notification,
        mock_send_user_email,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """The email notification payload includes the processed attachments."""
        attachments = [
            _make_upload_file("img1.png", "image/png", b"data1"),
        ]

        with patch("app.services.support_service.log"):
            result = await create_support_request_with_attachments(
                request_data=sample_request_data,
                attachments=attachments,
                user_id=USER_ID,
                user_email=USER_EMAIL,
                user_name=USER_NAME,
            )

        notification = mock_send_team_notification.await_args.args[0]
        assert isinstance(notification, SupportEmailNotification)
        assert notification.user_name == USER_NAME
        assert notification.user_email == USER_EMAIL
        assert notification.ticket_id == result.ticket_id
        assert notification.type is SupportRequestType.SUPPORT
        assert notification.support_emails == SUPPORT_EMAILS
        assert len(notification.attachments) == 1
        assert notification.attachments[0].filename == "img1.png"
        assert (
            notification.attachments[0].file_url
            == "https://res.cloudinary.com/demo/support/ticket_file.png"
        )
        mock_send_user_email.assert_awaited_once_with(notification)

    async def test_empty_attachments_metadata_exact(
        self,
        mock_support_repo,
        mock_email_notifications,
        sample_request_data,
    ):
        """No attachments still records the web-form-with-images source with image_count 0."""
        with patch("app.services.support_service.log"):
            await create_support_request_with_attachments(
                request_data=sample_request_data,
                attachments=[],
                user_id=USER_ID,
                user_email=USER_EMAIL,
            )

        stored = mock_support_repo.create.await_args.args[0]
        assert stored.attachments == []
        assert stored.metadata == {
            "source": "web_form_with_images",
            "user_agent": None,
            "image_count": 0,
        }

    async def test_user_name_defaults_to_user_with_attachments(
        self,
        mock_support_repo,
        mock_send_team_notification,
        mock_send_user_email,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """With attachments, a missing user_name still resolves to 'User' in emails."""
        attachments = [
            _make_upload_file("img1.png", "image/png", b"data"),
        ]

        with patch("app.services.support_service.log"):
            await create_support_request_with_attachments(
                request_data=sample_request_data,
                attachments=attachments,
                user_id=USER_ID,
                user_email=USER_EMAIL,
            )

        notification = mock_send_team_notification.await_args.args[0]
        assert notification.user_name == "User"
        stored = mock_support_repo.create.await_args.args[0]
        assert stored.user_name is None

    async def test_created_at_is_the_utc_now_value_with_attachments(
        self,
        mock_support_repo,
        mock_email_notifications,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """With attachments, created_at is exactly datetime.now(UTC) at creation time."""
        fixed_now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        attachments = [
            _make_upload_file("img1.png", "image/png", b"data"),
        ]

        with patch("app.services.support_service.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            with patch("app.services.support_service.log"):
                result = await create_support_request_with_attachments(
                    request_data=sample_request_data,
                    attachments=attachments,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        stored = mock_support_repo.create.await_args.args[0]
        assert stored.created_at == fixed_now
        assert stored.attachments[0].uploaded_at == fixed_now
        assert result.support_request.created_at == fixed_now
        # The UTC tz argument is pinned: a naive now() would silently produce
        # an unaware created_at.
        mock_dt.now.assert_any_call(UTC)

    async def test_success_with_empty_attachments(
        self,
        mock_support_repo,
        mock_email_notifications,
        sample_request_data,
    ):
        """No attachments provided still creates the request."""
        with patch("app.services.support_service.log"):
            result = await create_support_request_with_attachments(
                request_data=sample_request_data,
                attachments=[],
                user_id=USER_ID,
                user_email=USER_EMAIL,
            )

        assert result.success is True

    async def test_too_many_attachments_raises_400(self, sample_request_data):
        """More than 5 attachments raises 400."""
        attachments = [_make_upload_file(f"img{i}.png", "image/png", b"data") for i in range(6)]

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await create_support_request_with_attachments(
                    request_data=sample_request_data,
                    attachments=attachments,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        assert exc_info.value.status_code == 400
        assert "5" in exc_info.value.detail

    async def test_too_many_attachments_exact_detail_no_side_effects(
        self,
        sample_request_data,
        mock_support_repo,
        mock_cloudinary,
    ):
        """The 400 detail is exact and nothing is created, uploaded, or deleted."""
        attachments = [_make_upload_file(f"img{i}.png", "image/png", b"data") for i in range(6)]

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await create_support_request_with_attachments(
                    request_data=sample_request_data,
                    attachments=attachments,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Maximum 5 images allowed"
        mock_support_repo.create.assert_not_awaited()
        mock_support_repo.delete.assert_not_awaited()
        mock_cloudinary.destroy.assert_not_called()

    async def test_http_exception_from_upload_re_raised_clean(
        self,
        sample_request_data,
        mock_support_repo,
        mock_cloudinary,
    ):
        """A per-attachment validation failure propagates with no DB writes or deletes."""
        attachments = [
            _make_upload_file("doc.pdf", "application/pdf", b"data"),
        ]

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await create_support_request_with_attachments(
                    request_data=sample_request_data,
                    attachments=attachments,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        assert exc_info.value.status_code == 400
        assert "not allowed" in exc_info.value.detail
        mock_support_repo.create.assert_not_awaited()
        mock_support_repo.delete.assert_not_awaited()
        mock_cloudinary.destroy.assert_not_called()

    async def test_upload_failure_raises_500_with_failing_filename(
        self,
        sample_request_data,
        mock_support_repo,
    ):
        """When one upload fails, the 500 names the failing file and no document is created."""

        def _upload(public_id: str, file_data: bytes) -> str:
            if public_id.endswith("b.png"):
                raise RuntimeError("Cloudinary down")
            return "https://res.cloudinary.com/demo/upload/support/T1_ok.png"

        attachments = [
            _make_upload_file("a.png", "image/png", b"data"),
            _make_upload_file("b.png", "image/png", b"data"),
        ]

        with patch(
            "app.services.support_service.upload_file_to_cloudinary",
            side_effect=_upload,
        ):
            with patch("app.services.support_service.log") as mock_log:
                with pytest.raises(HTTPException) as exc_info:
                    await create_support_request_with_attachments(
                        request_data=sample_request_data,
                        attachments=attachments,
                        user_id=USER_ID,
                        user_email=USER_EMAIL,
                    )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to upload image b.png"
        mock_support_repo.create.assert_not_awaited()
        mock_support_repo.delete.assert_not_awaited()
        error_calls = [str(c) for c in mock_log.error.call_args_list]
        assert any("Failed to upload image" in call for call in error_calls)

    async def test_exactly_five_attachments_succeeds(
        self,
        mock_support_repo,
        mock_email_notifications,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """Exactly 5 attachments should be accepted."""
        attachments = [_make_upload_file(f"img{i}.png", "image/png", b"data") for i in range(5)]

        with patch("app.services.support_service.log"):
            result = await create_support_request_with_attachments(
                request_data=sample_request_data,
                attachments=attachments,
                user_id=USER_ID,
                user_email=USER_EMAIL,
            )

        assert result.success is True

    async def test_upload_failure_cleans_up_partial_uploads(
        self,
        sample_request_data,
    ):
        """If upload fails, already-uploaded files are cleaned up."""
        # We need to test that _delete_uploaded_files is called when
        # asyncio.gather fails. Since gather runs all tasks, we simulate
        # a failure by making _upload_single_attachment raise.
        with patch(
            "app.services.support_service._upload_single_attachment",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=400, detail="bad file"),
        ):
            with patch(
                "app.services.support_service._delete_uploaded_files",
                new_callable=AsyncMock,
            ):
                with patch("app.services.support_service.log"):
                    attachments = [
                        _make_upload_file("img1.png", "image/png", b"data"),
                    ]

                    with pytest.raises(HTTPException) as exc_info:
                        await create_support_request_with_attachments(
                            request_data=sample_request_data,
                            attachments=attachments,
                            user_id=USER_ID,
                            user_email=USER_EMAIL,
                        )

                    assert exc_info.value.status_code == 400

    async def test_db_failure_cleans_up_uploaded_files(
        self,
        mock_support_repo,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """When the repository create fails, uploaded files are cleaned up."""
        mock_support_repo.create.side_effect = RuntimeError("write failed")

        attachments = [
            _make_upload_file("img1.png", "image/png", b"data"),
        ]

        with patch(
            "app.services.support_service._delete_uploaded_files",
            new_callable=AsyncMock,
        ) as mock_delete:
            with patch("app.services.support_service.log"):
                with pytest.raises(HTTPException) as exc_info:
                    await create_support_request_with_attachments(
                        request_data=sample_request_data,
                        attachments=attachments,
                        user_id=USER_ID,
                        user_email=USER_EMAIL,
                    )

        assert exc_info.value.status_code == 500
        mock_delete.assert_awaited_once()

    async def test_db_failure_without_uploads_skips_file_cleanup(
        self,
        mock_support_repo,
        sample_request_data,
    ):
        """A DB failure with no uploaded files rolls back the DB entry but never
        touches Cloudinary: file cleanup only runs when files were uploaded."""
        mock_support_repo.create.side_effect = RuntimeError("write failed")

        with patch(
            "app.services.support_service._delete_uploaded_files",
            new_callable=AsyncMock,
        ) as mock_delete_files:
            with patch("app.services.support_service.log") as mock_log:
                with pytest.raises(HTTPException) as exc_info:
                    await create_support_request_with_attachments(
                        request_data=sample_request_data,
                        attachments=[],
                        user_id=USER_ID,
                        user_email=USER_EMAIL,
                    )

        assert exc_info.value.status_code == 500
        # No files were uploaded, so no Cloudinary cleanup happens...
        mock_delete_files.assert_not_awaited()
        # ...but the database rollback still runs.
        mock_support_repo.delete.assert_awaited_once()
        assert not any(
            c.args and c.args[0] == "Cleaned up uploaded files due to unexpected error"
            for c in mock_log.info.call_args_list
        )

    async def test_db_failure_cleans_up_exact_url_via_real_delete(
        self,
        mock_support_repo,
        mock_upload_file_to_cloudinary,
        mock_cloudinary,
        sample_request_data,
    ):
        """Repository failure deletes exactly the uploaded URL and rolls back nothing else."""
        mock_support_repo.create.side_effect = RuntimeError("write failed")

        attachments = [
            _make_upload_file("img1.png", "image/png", b"data"),
        ]

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await create_support_request_with_attachments(
                    request_data=sample_request_data,
                    attachments=attachments,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to create support request: write failed"
        mock_cloudinary.destroy.assert_called_once_with("support/ticket_file")
        mock_support_repo.delete.assert_awaited_once()
        assert uuid.UUID(mock_support_repo.delete.await_args.args[0])

    async def test_email_failure_cleans_up_files_and_db(
        self,
        mock_support_repo,
        mock_send_team_notification,
        mock_send_user_email,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """Email failure triggers cleanup of both files and DB entry."""
        mock_send_team_notification.side_effect = Exception("SMTP fail")

        attachments = [
            _make_upload_file("img1.png", "image/png", b"data"),
        ]

        with patch(
            "app.services.support_service._delete_uploaded_files",
            new_callable=AsyncMock,
        ) as mock_delete_files:
            with patch("app.services.support_service.log") as mock_log:
                with pytest.raises(HTTPException) as exc_info:
                    await create_support_request_with_attachments(
                        request_data=sample_request_data,
                        attachments=attachments,
                        user_id=USER_ID,
                        user_email=USER_EMAIL,
                    )

        assert exc_info.value.status_code == 500
        # Files should be cleaned up
        mock_delete_files.assert_awaited_once()
        # DB entry should be rolled back
        mock_support_repo.delete.assert_awaited_once()
        created = mock_support_repo.create.await_args.args[0]
        ticket_id = created.ticket_id
        mock_delete_files.assert_awaited_once_with(
            ["https://res.cloudinary.com/demo/support/ticket_file.png"]
        )
        mock_log.error.assert_any_call(
            "Email sending failed for ticket",
            ticket_id=ticket_id,
            error="SMTP fail",
            error_type="Exception",
            user_id=USER_ID,
        )
        mock_log.info.assert_has_calls(
            [
                call.info(
                    "Successfully cleaned up uploaded files for ticket",
                    attachment_urls_count=1,
                    ticket_id=ticket_id,
                ),
                call.info(
                    "Successfully rolled back support request from database", ticket_id=ticket_id
                ),
            ]
        )

    async def test_email_failure_cleans_up_exact_url_and_db(
        self,
        mock_support_repo,
        mock_send_team_notification,
        mock_send_user_email,
        mock_upload_file_to_cloudinary,
        mock_cloudinary,
        sample_request_data,
    ):
        """Email failure deletes exactly the uploaded URL and rolls back the exact document id."""
        mock_send_team_notification.side_effect = Exception("SMTP fail")

        attachments = [
            _make_upload_file("img1.png", "image/png", b"data"),
        ]

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await create_support_request_with_attachments(
                    request_data=sample_request_data,
                    attachments=attachments,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        assert exc_info.value.status_code == 500
        assert (
            exc_info.value.detail
            == "Failed to send email notifications. Support request was not created. Please try again."
        )
        mock_cloudinary.destroy.assert_called_once_with("support/ticket_file")
        created_id = mock_support_repo.create.await_args.args[0].id
        mock_support_repo.delete.assert_awaited_once_with(created_id, user_id=USER_ID)

    async def test_email_failure_file_cleanup_error_still_rolls_back_db(
        self,
        mock_support_repo,
        mock_send_team_notification,
        mock_send_user_email,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """If file cleanup fails during email rollback, DB rollback still happens."""
        mock_send_team_notification.side_effect = Exception("SMTP fail")

        attachments = [
            _make_upload_file("img1.png", "image/png", b"data"),
        ]

        with patch(
            "app.services.support_service._delete_uploaded_files",
            new_callable=AsyncMock,
            side_effect=Exception("cleanup failed"),
        ):
            with patch("app.services.support_service.log") as mock_log:
                with pytest.raises(HTTPException):
                    await create_support_request_with_attachments(
                        request_data=sample_request_data,
                        attachments=attachments,
                        user_id=USER_ID,
                        user_email=USER_EMAIL,
                    )

        # DB rollback should still be attempted
        mock_support_repo.delete.assert_awaited_once()
        ticket_id = mock_support_repo.create.await_args.args[0].ticket_id
        mock_log.error.assert_any_call(
            "Error cleaning up uploaded files for ticket",
            ticket_id=ticket_id,
            error="cleanup failed",
            error_type="Exception",
            user_id=USER_ID,
        )

    async def test_email_failure_db_rollback_not_deleted(
        self,
        mock_support_repo,
        mock_send_team_notification,
        mock_send_user_email,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """When DB rollback finds nothing to delete, an error is logged."""
        mock_support_repo.delete.return_value = False
        mock_send_team_notification.side_effect = Exception("SMTP fail")

        attachments = [
            _make_upload_file("img1.png", "image/png", b"data"),
        ]

        with patch(
            "app.services.support_service._delete_uploaded_files",
            new_callable=AsyncMock,
        ):
            with patch("app.services.support_service.log") as mock_log:
                with pytest.raises(HTTPException):
                    await create_support_request_with_attachments(
                        request_data=sample_request_data,
                        attachments=attachments,
                        user_id=USER_ID,
                        user_email=USER_EMAIL,
                    )

                ticket_id = mock_support_repo.create.await_args.args[0].ticket_id
                mock_log.error.assert_any_call(
                    "Failed to rollback support request from database",
                    ticket_id=ticket_id,
                    error="SMTP fail",
                    error_type="Exception",
                    user_id=USER_ID,
                )

    async def test_email_failure_db_rollback_error_logged(
        self,
        mock_support_repo,
        mock_send_team_notification,
        mock_send_user_email,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """When the rollback delete itself fails, the database rollback error is logged."""
        mock_support_repo.delete.side_effect = Exception("DB unreachable")
        mock_send_team_notification.side_effect = Exception("SMTP fail")

        attachments = [
            _make_upload_file("img1.png", "image/png", b"data"),
        ]

        with patch(
            "app.services.support_service._delete_uploaded_files",
            new_callable=AsyncMock,
        ):
            with patch("app.services.support_service.log") as mock_log:
                with pytest.raises(HTTPException):
                    await create_support_request_with_attachments(
                        request_data=sample_request_data,
                        attachments=attachments,
                        user_id=USER_ID,
                        user_email=USER_EMAIL,
                    )

        ticket_id = mock_support_repo.create.await_args.args[0].ticket_id
        mock_log.error.assert_any_call(
            "Error during database rollback for ticket",
            ticket_id=ticket_id,
            error="DB unreachable",
            error_type="Exception",
            user_id=USER_ID,
        )

    async def test_unexpected_error_cleans_up_everything(
        self,
        mock_support_repo,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """An unexpected (non-HTTP) error triggers full cleanup of files and DB."""
        attachments = [
            _make_upload_file("img1.png", "image/png", b"data"),
        ]

        # Make email notification succeed, but the response construction fail
        with patch(
            "app.services.support_service._send_support_email_notifications",
            new_callable=AsyncMock,
        ):
            with patch(
                "app.services.support_service.SupportRequestResponse.model_validate",
                side_effect=RuntimeError("unexpected model error"),
            ):
                with patch(
                    "app.services.support_service._delete_uploaded_files",
                    new_callable=AsyncMock,
                ) as mock_delete_files:
                    with patch("app.services.support_service.log") as mock_log:
                        with pytest.raises(HTTPException) as exc_info:
                            await create_support_request_with_attachments(
                                request_data=sample_request_data,
                                attachments=attachments,
                                user_id=USER_ID,
                                user_email=USER_EMAIL,
                            )

        assert exc_info.value.status_code == 500
        mock_delete_files.assert_awaited_once()
        mock_support_repo.delete.assert_awaited_once()
        created = mock_support_repo.create.await_args.args[0]
        mock_delete_files.assert_awaited_once_with(
            ["https://res.cloudinary.com/demo/support/ticket_file.png"]
        )
        mock_log.error.assert_called_once_with(
            "Unexpected error creating support request with images",
            error="unexpected model error",
            error_type="RuntimeError",
            user_id=USER_ID,
        )
        mock_log.info.assert_has_calls(
            [
                call.info(
                    "Cleaned up uploaded files due to unexpected error",
                    attachment_urls_count=1,
                ),
                call.info(
                    "Rolled back support request due to unexpected error", request_id=created.id
                ),
            ]
        )

    async def test_unexpected_error_cleans_up_exact_url_and_db(
        self,
        mock_support_repo,
        mock_upload_file_to_cloudinary,
        mock_cloudinary,
        sample_request_data,
    ):
        """An unexpected error deletes exactly the uploaded URL and the exact document id."""
        attachments = [
            _make_upload_file("img1.png", "image/png", b"data"),
        ]

        with patch(
            "app.services.support_service._send_support_email_notifications",
            new_callable=AsyncMock,
        ):
            with patch(
                "app.services.support_service.SupportRequestResponse.model_validate",
                side_effect=RuntimeError("unexpected model error"),
            ):
                with patch("app.services.support_service.log"):
                    with pytest.raises(HTTPException) as exc_info:
                        await create_support_request_with_attachments(
                            request_data=sample_request_data,
                            attachments=attachments,
                            user_id=USER_ID,
                            user_email=USER_EMAIL,
                        )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to create support request: unexpected model error"
        mock_cloudinary.destroy.assert_called_once_with("support/ticket_file")
        created_id = mock_support_repo.create.await_args.args[0].id
        mock_support_repo.delete.assert_awaited_once_with(created_id, user_id=USER_ID)

    async def test_unexpected_error_cleanup_failures_still_raises_500(
        self,
        mock_support_repo,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """Even when both file cleanup and DB rollback fail, 500 is raised."""
        mock_support_repo.delete.side_effect = Exception("DB gone")

        attachments = [
            _make_upload_file("img1.png", "image/png", b"data"),
        ]

        with patch(
            "app.services.support_service._send_support_email_notifications",
            new_callable=AsyncMock,
        ):
            with patch(
                "app.services.support_service.SupportRequestResponse.model_validate",
                side_effect=RuntimeError("unexpected"),
            ):
                with patch(
                    "app.services.support_service._delete_uploaded_files",
                    new_callable=AsyncMock,
                    side_effect=Exception("cleanup gone"),
                ):
                    with patch("app.services.support_service.log") as mock_log:
                        with pytest.raises(HTTPException) as exc_info:
                            await create_support_request_with_attachments(
                                request_data=sample_request_data,
                                attachments=attachments,
                                user_id=USER_ID,
                                user_email=USER_EMAIL,
                            )

        assert exc_info.value.status_code == 500
        created_id = mock_support_repo.create.await_args.args[0].id
        mock_log.error.assert_any_call(
            "Error cleaning up uploaded files",
            error="cleanup gone",
            error_type="Exception",
            user_id=USER_ID,
        )
        mock_log.error.assert_any_call(
            "Error during rollback for request",
            request_id=created_id,
            error="DB gone",
            error_type="Exception",
            user_id=USER_ID,
        )


# ===========================================================================
# _send_support_email_notifications
# ===========================================================================


class TestSendSupportEmailNotifications:
    @pytest.fixture
    def notification_data(self):
        return SupportEmailNotification(
            user_name=USER_NAME,
            user_email=USER_EMAIL,
            ticket_id=TICKET_ID,
            type=SupportRequestType.SUPPORT,
            title="Test Ticket",
            description="A description for the test ticket.",
            created_at=datetime.now(UTC),
            support_emails=SUPPORT_EMAILS,
            attachments=[],
        )

    async def test_success_sends_team_and_user_emails(
        self,
        mock_send_team_notification,
        mock_send_user_email,
        notification_data,
    ):
        """Both team and user emails are sent on success."""
        await _send_support_email_notifications(notification_data)

        mock_send_team_notification.assert_awaited_once_with(notification_data)
        mock_send_user_email.assert_awaited_once_with(notification_data)

    async def test_team_email_failure_stops_user_email(
        self,
        mock_send_team_notification,
        mock_send_user_email,
        notification_data,
    ):
        """When team email fails, user email is never attempted."""
        mock_send_team_notification.side_effect = Exception("SMTP error")

        with patch("app.services.support_service.log"):
            with pytest.raises(Exception, match="SMTP error"):
                await _send_support_email_notifications(notification_data)

        mock_send_user_email.assert_not_awaited()

    async def test_team_email_failure_logs_exact_error(
        self,
        mock_send_team_notification,
        mock_send_user_email,
        notification_data,
    ):
        """Team email failure logs the exact error context."""
        mock_send_team_notification.side_effect = Exception("SMTP error")

        with patch("app.services.support_service.log") as mock_log:
            with pytest.raises(Exception, match="SMTP error"):
                await _send_support_email_notifications(notification_data)

        mock_log.error.assert_called_once_with(
            "Error sending email notifications", error="SMTP error", error_type="Exception"
        )

    async def test_user_email_failure_logs_exact_error(
        self,
        mock_send_team_notification,
        mock_send_user_email,
        notification_data,
    ):
        """User email failure logs the exact error context."""
        mock_send_user_email.side_effect = Exception("user SMTP error")

        with patch("app.services.support_service.log") as mock_log:
            with pytest.raises(Exception, match="user SMTP error"):
                await _send_support_email_notifications(notification_data)

        mock_log.error.assert_called_once_with(
            "Error sending email notifications",
            error="user SMTP error",
            error_type="Exception",
        )

    async def test_user_email_failure_re_raises(
        self,
        mock_send_team_notification,
        mock_send_user_email,
        notification_data,
    ):
        """When user email fails (team succeeded), the exception propagates."""
        mock_send_user_email.side_effect = Exception("user SMTP error")

        with patch("app.services.support_service.log"):
            with pytest.raises(Exception, match="user SMTP error"):
                await _send_support_email_notifications(notification_data)

        # Team email was still sent
        mock_send_team_notification.assert_awaited_once()


# ===========================================================================
# get_user_support_requests
# ===========================================================================


class TestGetUserSupportRequests:
    async def test_success_returns_requests_and_pagination(
        self,
        mock_support_repo,
    ):
        """Returns correctly formatted response with pagination."""
        mock_support_repo.page_for_user.return_value = [_make_support_doc()]
        mock_support_repo.count_for_user_status.return_value = 1

        with patch("app.services.support_service.log"):
            result = await get_user_support_requests(user_id=USER_ID, page=1, per_page=10)

        assert len(result.requests) == 1
        assert isinstance(result.requests[0], SupportRequestResponse)
        assert result.pagination.page == 1
        assert result.pagination.per_page == 10
        assert result.pagination.total == 1
        assert result.pagination.pages == 1

    async def test_defaults_page_per_page_and_status_filter(self, mock_support_repo):
        """Omitting page/per_page/status uses page 1, 10 per page, and no filter."""
        mock_support_repo.page_for_user.return_value = []
        mock_support_repo.count_for_user_status.return_value = 0

        with patch("app.services.support_service.log"):
            result = await get_user_support_requests(user_id=USER_ID)

        assert result.pagination.page == 1
        assert result.pagination.per_page == 10
        page_call = mock_support_repo.page_for_user.await_args
        assert page_call.args[0] == USER_ID
        assert page_call.kwargs["status"] is None
        assert page_call.kwargs["skip"] == 0
        assert page_call.kwargs["limit"] == 10
        count_call = mock_support_repo.count_for_user_status.await_args
        assert count_call.args[0] == USER_ID
        assert count_call.kwargs["status"] is None

    async def test_pagination_exact_multiple_rounds_to_whole_pages(self, mock_support_repo):
        """A total that divides per_page evenly yields exact page count."""
        mock_support_repo.page_for_user.return_value = []
        mock_support_repo.count_for_user_status.return_value = 10

        with patch("app.services.support_service.log"):
            result = await get_user_support_requests(user_id=USER_ID, page=1, per_page=10)

        assert result.pagination.pages == 1

    async def test_pagination_rounds_up_partial_page(self, mock_support_repo):
        """A partial final page rounds up."""
        mock_support_repo.page_for_user.return_value = []
        mock_support_repo.count_for_user_status.return_value = 11

        with patch("app.services.support_service.log"):
            result = await get_user_support_requests(user_id=USER_ID, page=1, per_page=10)

        assert result.pagination.pages == 2

    async def test_pagination_skip_for_page_two(self, mock_support_repo):
        """Page 2 skips one full page."""
        mock_support_repo.page_for_user.return_value = []
        mock_support_repo.count_for_user_status.return_value = 30

        with patch("app.services.support_service.log"):
            await get_user_support_requests(user_id=USER_ID, page=2, per_page=15)

        page_call = mock_support_repo.page_for_user.await_args
        assert page_call.kwargs["skip"] == 15
        assert page_call.kwargs["limit"] == 15

    async def test_response_exact_fields(self, mock_support_repo):
        """Response fields mirror the repository document exactly."""
        mock_support_repo.page_for_user.return_value = [_make_support_doc()]
        mock_support_repo.count_for_user_status.return_value = 1

        with patch("app.services.support_service.log"):
            result = await get_user_support_requests(user_id=USER_ID, page=1, per_page=10)

        req = result.requests[0]
        assert req.id == REQUEST_ID
        assert req.ticket_id == TICKET_ID
        assert req.user_id == USER_ID
        assert req.user_email == USER_EMAIL
        assert req.type is SupportRequestType.SUPPORT
        assert req.status is SupportRequestStatus.OPEN
        assert req.priority is SupportRequestPriority.MEDIUM

    async def test_with_status_filter(self, mock_support_repo):
        """Status filter is passed through to the repository."""
        mock_support_repo.page_for_user.return_value = []
        mock_support_repo.count_for_user_status.return_value = 0

        with patch("app.services.support_service.log"):
            result = await get_user_support_requests(
                user_id=USER_ID,
                page=1,
                per_page=10,
                status_filter=SupportRequestStatus.RESOLVED,
            )

        # Both the page and count queries receive the status filter.
        assert (
            mock_support_repo.page_for_user.await_args.kwargs["status"]
            is SupportRequestStatus.RESOLVED
        )
        assert (
            mock_support_repo.count_for_user_status.await_args.kwargs["status"]
            is SupportRequestStatus.RESOLVED
        )
        assert mock_support_repo.page_for_user.await_args.args[0] == USER_ID
        assert result.requests == []

    async def test_empty_results(self, mock_support_repo):
        """No matching documents returns empty list."""
        mock_support_repo.page_for_user.return_value = []
        mock_support_repo.count_for_user_status.return_value = 0

        with patch("app.services.support_service.log"):
            result = await get_user_support_requests(user_id=USER_ID, page=1, per_page=10)

        assert result.requests == []
        assert result.pagination.total == 0
        assert result.pagination.pages == 0

    async def test_pagination_calculation(self, mock_support_repo):
        """Pagination pages are calculated correctly with ceiling division."""
        mock_support_repo.page_for_user.return_value = []
        mock_support_repo.count_for_user_status.return_value = 25

        with patch("app.services.support_service.log"):
            result = await get_user_support_requests(user_id=USER_ID, page=2, per_page=10)

        assert result.pagination.pages == 3
        assert result.pagination.page == 2

    async def test_pagination_skip_value(self, mock_support_repo):
        """The repository page query uses the correct skip/limit for page 3."""
        mock_support_repo.page_for_user.return_value = []
        mock_support_repo.count_for_user_status.return_value = 50

        with patch("app.services.support_service.log"):
            await get_user_support_requests(user_id=USER_ID, page=3, per_page=10)

        page_call = mock_support_repo.page_for_user.await_args
        assert page_call.kwargs["skip"] == 20
        assert page_call.kwargs["limit"] == 10

    async def test_db_error_raises_500(self, mock_support_repo):
        """Database error raises 500."""
        mock_support_repo.count_for_user_status.side_effect = Exception("DB error")

        with patch("app.services.support_service.log") as mock_log:
            with pytest.raises(HTTPException) as exc_info:
                await get_user_support_requests(user_id=USER_ID)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to fetch support requests"
        mock_log.error.assert_called_once_with(
            "Error fetching user support requests",
            error="DB error",
            error_type="Exception",
            user_id=USER_ID,
        )

    async def test_page_for_user_error_raises_500(self, mock_support_repo):
        """An error from the page query also raises 500 with the exact detail."""
        mock_support_repo.page_for_user.side_effect = Exception("DB error")

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await get_user_support_requests(user_id=USER_ID)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to fetch support requests"

    async def test_multiple_documents_returned(self, mock_support_repo):
        """Multiple documents are all converted to response models."""
        docs = [_make_support_doc(request_id=f"id-{i}", ticket_id=f"T-{i}") for i in range(3)]
        mock_support_repo.page_for_user.return_value = docs
        mock_support_repo.count_for_user_status.return_value = 3

        with patch("app.services.support_service.log"):
            result = await get_user_support_requests(user_id=USER_ID, page=1, per_page=10)

        assert len(result.requests) == 3
        for req in result.requests:
            assert isinstance(req, SupportRequestResponse)
