"""Unit tests for the support service (app/services/support_service.py)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from app.models.support_models import (
    SupportEmailNotification,
    SupportRequestCreate,
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
    get_all_support_requests,
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
def mock_support_collection():
    with patch("app.services.support_service.support_collection") as mock_col:
        yield mock_col


@pytest.fixture
def mock_cloudinary():
    with patch("app.services.support_service.cloudinary.uploader") as mock_uploader:
        yield mock_uploader


@pytest.fixture
def mock_upload_file_to_cloudinary():
    with patch("app.services.support_service.upload_file_to_cloudinary") as mock_upload:
        mock_upload.return_value = (
            "https://res.cloudinary.com/demo/support/ticket_file.png"
        )
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


def _make_db_support_doc(
    request_id: str = REQUEST_ID,
    ticket_id: str = TICKET_ID,
    req_type: str = "support",
) -> dict:
    """Create a support request document as it would exist in MongoDB."""
    now = datetime.now(timezone.utc)
    return {
        "_id": request_id,
        "ticket_id": ticket_id,
        "user_id": USER_ID,
        "user_email": USER_EMAIL,
        "user_name": USER_NAME,
        "type": req_type,
        "title": "Test Request",
        "description": "A test support request with enough characters.",
        "status": "open",
        "priority": "medium",
        "created_at": now,
        "updated_at": now,
        "resolved_at": None,
        "tags": [],
        "metadata": {"source": "web_form", "user_agent": None},
    }


# ===========================================================================
# _delete_uploaded_files
# ===========================================================================


@pytest.mark.unit
class TestDeleteUploadedFiles:
    async def test_success_deletion(self, mock_cloudinary):
        """Cloudinary destroy is called and succeeds for a well-formed URL."""
        mock_cloudinary.destroy.return_value = {"result": "ok"}

        urls = ["https://res.cloudinary.com/demo/image/upload/support/TICKET_file.png"]
        await _delete_uploaded_files(urls, "TICKET")

        mock_cloudinary.destroy.assert_called_once_with("support/TICKET_file")

    async def test_malformed_url_without_support_segment_is_skipped(
        self, mock_cloudinary
    ):
        """URLs that do not contain 'support/' are silently skipped."""
        urls = ["https://example.com/other/path/file.png"]
        await _delete_uploaded_files(urls, "TICKET")

        mock_cloudinary.destroy.assert_not_called()

    async def test_support_segment_at_end_without_filename_is_skipped(
        self, mock_cloudinary
    ):
        """URL where 'support' is the last segment (no filename after it) is skipped."""
        urls = ["https://res.cloudinary.com/demo/image/upload/support"]
        await _delete_uploaded_files(urls, "TICKET")

        mock_cloudinary.destroy.assert_not_called()

    async def test_cloudinary_result_not_ok_logs_warning(self, mock_cloudinary):
        """When Cloudinary returns a result other than 'ok', a warning is logged."""
        mock_cloudinary.destroy.return_value = {"result": "not found"}

        urls = ["https://res.cloudinary.com/demo/image/upload/support/TICKET_file.png"]
        with patch("app.services.support_service.log") as mock_log:
            await _delete_uploaded_files(urls, "TICKET")

            mock_log.warning.assert_called_once()
            assert "Failed to delete" in mock_log.warning.call_args[0][0]

    async def test_exception_during_destroy_is_logged(self, mock_cloudinary):
        """Exceptions from Cloudinary are caught and logged, not re-raised."""
        mock_cloudinary.destroy.side_effect = Exception("network error")

        urls = ["https://res.cloudinary.com/demo/image/upload/support/TICKET_file.png"]
        with patch("app.services.support_service.log") as mock_log:
            await _delete_uploaded_files(urls, "TICKET")

            mock_log.error.assert_called_once()
            assert "network error" in mock_log.error.call_args[0][0]

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
            await _delete_uploaded_files(urls, "TICKET")

        assert mock_cloudinary.destroy.call_count == 3

    async def test_empty_url_list_does_nothing(self, mock_cloudinary):
        """An empty URL list results in no Cloudinary calls."""
        await _delete_uploaded_files([], "TICKET")
        mock_cloudinary.destroy.assert_not_called()


# ===========================================================================
# _upload_single_attachment
# ===========================================================================


@pytest.mark.unit
class TestUploadSingleAttachment:
    async def test_success_upload(self, mock_upload_file_to_cloudinary):
        """Happy path: valid file is uploaded and metadata is returned."""
        upload = _make_upload_file(
            filename="screenshot.png",
            content_type="image/png",
            content=b"x" * 100,
        )
        current_time = datetime.now(timezone.utc)

        file_url, attachment_meta = await _upload_single_attachment(
            attachment=upload,
            ticket_id="T1",
            current_time=current_time,
            allowed_types=ALLOWED_TYPES,
            max_file_size=MAX_FILE_SIZE,
        )

        assert file_url == mock_upload_file_to_cloudinary.return_value
        assert attachment_meta["filename"] == "screenshot.png"
        assert attachment_meta["file_size"] == 100
        assert attachment_meta["content_type"] == "image/png"
        assert attachment_meta["file_url"] == file_url

    async def test_wrong_content_type_raises_400(self):
        """Non-image content type raises 400."""
        upload = _make_upload_file(
            filename="doc.pdf",
            content_type="application/pdf",
        )
        current_time = datetime.now(timezone.utc)

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
        current_time = datetime.now(timezone.utc)

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
        current_time = datetime.now(timezone.utc)

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
        current_time = datetime.now(timezone.utc)

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

    async def test_file_exactly_at_max_size_succeeds(
        self, mock_upload_file_to_cloudinary
    ):
        """File exactly at max size should succeed."""
        content = b"x" * MAX_FILE_SIZE
        upload = _make_upload_file(
            filename="exact.png",
            content_type="image/png",
            content=content,
        )
        current_time = datetime.now(timezone.utc)

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
        current_time = datetime.now(timezone.utc)

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

    async def test_all_allowed_types_accepted(self, mock_upload_file_to_cloudinary):
        """Each allowed content type can be uploaded."""
        for ctype in ALLOWED_TYPES:
            upload = _make_upload_file(
                filename=f"file.{ctype.split('/')[-1]}",
                content_type=ctype,
                content=b"data",
            )
            current_time = datetime.now(timezone.utc)

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


@pytest.mark.unit
class TestCreateSupportRequest:
    async def test_success(
        self,
        mock_support_collection,
        mock_email_notifications,
        sample_request_data,
    ):
        """Happy path: DB insert succeeds, emails succeed, response returned."""
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = REQUEST_ID
        mock_support_collection.insert_one = AsyncMock(return_value=mock_insert_result)

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
        mock_support_collection.insert_one.assert_awaited_once()

    async def test_db_insertion_returns_no_inserted_id_raises_500(
        self,
        mock_support_collection,
        sample_request_data,
    ):
        """When insert_one returns falsy inserted_id, 500 is raised."""
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = None
        mock_support_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await create_support_request(
                    request_data=sample_request_data,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        assert exc_info.value.status_code == 500
        assert "Failed to create" in exc_info.value.detail

    async def test_email_failure_triggers_rollback_and_raises_500(
        self,
        mock_support_collection,
        mock_send_team_notification,
        mock_send_user_email,
        sample_request_data,
    ):
        """Email failure causes DB deletion (rollback) and raises 500."""
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = REQUEST_ID
        mock_support_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 1
        mock_support_collection.delete_one = AsyncMock(return_value=mock_delete_result)

        mock_send_team_notification.side_effect = Exception("SMTP error")

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await create_support_request(
                    request_data=sample_request_data,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        assert exc_info.value.status_code == 500
        assert "email" in exc_info.value.detail.lower()
        mock_support_collection.delete_one.assert_awaited_once()

    async def test_email_failure_rollback_fails_still_raises_500(
        self,
        mock_support_collection,
        mock_send_team_notification,
        mock_send_user_email,
        sample_request_data,
    ):
        """Even if rollback itself fails, the 500 is still raised."""
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = REQUEST_ID
        mock_support_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        mock_support_collection.delete_one = AsyncMock(
            side_effect=Exception("DB unreachable")
        )

        mock_send_team_notification.side_effect = Exception("SMTP error")

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await create_support_request(
                    request_data=sample_request_data,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        assert exc_info.value.status_code == 500

    async def test_email_failure_rollback_deleted_count_zero_logs_error(
        self,
        mock_support_collection,
        mock_send_team_notification,
        mock_send_user_email,
        sample_request_data,
    ):
        """When rollback delete returns 0 deleted_count, an error is logged."""
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = REQUEST_ID
        mock_support_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 0
        mock_support_collection.delete_one = AsyncMock(return_value=mock_delete_result)

        mock_send_team_notification.side_effect = Exception("SMTP error")

        with patch("app.services.support_service.log") as mock_log:
            with pytest.raises(HTTPException):
                await create_support_request(
                    request_data=sample_request_data,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

            # Verify that an error about failed rollback was logged
            error_calls = [str(c) for c in mock_log.error.call_args_list]
            assert any("Failed to rollback" in call for call in error_calls)

    async def test_unexpected_error_with_rollback(
        self,
        mock_support_collection,
        sample_request_data,
    ):
        """Unexpected exception after request_id is set triggers rollback."""
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = REQUEST_ID
        mock_support_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 1
        mock_support_collection.delete_one = AsyncMock(return_value=mock_delete_result)

        # Patch _send_support_email_notifications to raise a non-HTTP exception
        # that won't be caught by the inner try/except
        with patch(
            "app.services.support_service._send_support_email_notifications",
            new_callable=AsyncMock,
        ) as mock_notify:
            mock_notify.return_value = None
            # Cause an error in SupportRequestResponse construction
            with patch(
                "app.services.support_service.SupportRequestResponse",
                side_effect=RuntimeError("unexpected"),
            ):
                with patch("app.services.support_service.log"):
                    with pytest.raises(HTTPException) as exc_info:
                        await create_support_request(
                            request_data=sample_request_data,
                            user_id=USER_ID,
                            user_email=USER_EMAIL,
                        )

        assert exc_info.value.status_code == 500
        mock_support_collection.delete_one.assert_awaited_once()

    async def test_unexpected_error_rollback_failure_still_raises_500(
        self,
        mock_support_collection,
        sample_request_data,
    ):
        """When both the main operation and rollback fail, 500 is still raised."""
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = REQUEST_ID
        mock_support_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        mock_support_collection.delete_one = AsyncMock(
            side_effect=Exception("rollback failed")
        )

        with patch(
            "app.services.support_service._send_support_email_notifications",
            new_callable=AsyncMock,
        ):
            with patch(
                "app.services.support_service.SupportRequestResponse",
                side_effect=RuntimeError("unexpected"),
            ):
                with patch("app.services.support_service.log"):
                    with pytest.raises(HTTPException) as exc_info:
                        await create_support_request(
                            request_data=sample_request_data,
                            user_id=USER_ID,
                            user_email=USER_EMAIL,
                        )

        assert exc_info.value.status_code == 500

    async def test_user_name_defaults_to_user_in_email(
        self,
        mock_support_collection,
        mock_send_team_notification,
        mock_send_user_email,
        sample_request_data,
    ):
        """When user_name is None, 'User' is used in email notifications."""
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = REQUEST_ID
        mock_support_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        with patch("app.services.support_service.log"):
            result = await create_support_request(
                request_data=sample_request_data,
                user_id=USER_ID,
                user_email=USER_EMAIL,
                user_name=None,
            )

        assert result.success is True
        # The email notification should have been called with user_name="User"
        mock_send_team_notification.assert_awaited_once()


# ===========================================================================
# create_support_request_with_attachments
# ===========================================================================


@pytest.mark.unit
class TestCreateSupportRequestWithAttachments:
    async def test_success_with_attachments(
        self,
        mock_support_collection,
        mock_email_notifications,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """Happy path: files uploaded, DB insert, emails sent."""
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = REQUEST_ID
        mock_support_collection.insert_one = AsyncMock(return_value=mock_insert_result)

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

        assert isinstance(result, SupportRequestSubmissionResponse)
        assert result.success is True
        assert result.ticket_id is not None
        assert "images" in result.message.lower()
        mock_support_collection.insert_one.assert_awaited_once()

    async def test_success_with_empty_attachments(
        self,
        mock_support_collection,
        mock_email_notifications,
        sample_request_data,
    ):
        """No attachments provided still creates the request."""
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = REQUEST_ID
        mock_support_collection.insert_one = AsyncMock(return_value=mock_insert_result)

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
        attachments = [
            _make_upload_file(f"img{i}.png", "image/png", b"data") for i in range(6)
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
        assert "5" in exc_info.value.detail

    async def test_exactly_five_attachments_succeeds(
        self,
        mock_support_collection,
        mock_email_notifications,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """Exactly 5 attachments should be accepted."""
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = REQUEST_ID
        mock_support_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        attachments = [
            _make_upload_file(f"img{i}.png", "image/png", b"data") for i in range(5)
        ]

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
        mock_support_collection,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """When DB insert fails (no inserted_id), uploaded files are cleaned up."""
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = None
        mock_support_collection.insert_one = AsyncMock(return_value=mock_insert_result)

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

    async def test_email_failure_cleans_up_files_and_db(
        self,
        mock_support_collection,
        mock_send_team_notification,
        mock_send_user_email,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """Email failure triggers cleanup of both files and DB entry."""
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = REQUEST_ID
        mock_support_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 1
        mock_support_collection.delete_one = AsyncMock(return_value=mock_delete_result)

        mock_send_team_notification.side_effect = Exception("SMTP fail")

        attachments = [
            _make_upload_file("img1.png", "image/png", b"data"),
        ]

        with patch(
            "app.services.support_service._delete_uploaded_files",
            new_callable=AsyncMock,
        ) as mock_delete_files:
            with patch("app.services.support_service.log"):
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
        mock_support_collection.delete_one.assert_awaited_once()

    async def test_email_failure_file_cleanup_error_still_rolls_back_db(
        self,
        mock_support_collection,
        mock_send_team_notification,
        mock_send_user_email,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """If file cleanup fails during email rollback, DB rollback still happens."""
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = REQUEST_ID
        mock_support_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 1
        mock_support_collection.delete_one = AsyncMock(return_value=mock_delete_result)

        mock_send_team_notification.side_effect = Exception("SMTP fail")

        attachments = [
            _make_upload_file("img1.png", "image/png", b"data"),
        ]

        with patch(
            "app.services.support_service._delete_uploaded_files",
            new_callable=AsyncMock,
            side_effect=Exception("cleanup failed"),
        ):
            with patch("app.services.support_service.log"):
                with pytest.raises(HTTPException):
                    await create_support_request_with_attachments(
                        request_data=sample_request_data,
                        attachments=attachments,
                        user_id=USER_ID,
                        user_email=USER_EMAIL,
                    )

        # DB rollback should still be attempted
        mock_support_collection.delete_one.assert_awaited_once()

    async def test_email_failure_db_rollback_deleted_count_zero(
        self,
        mock_support_collection,
        mock_send_team_notification,
        mock_send_user_email,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """When DB rollback returns deleted_count=0, error is logged."""
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = REQUEST_ID
        mock_support_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 0
        mock_support_collection.delete_one = AsyncMock(return_value=mock_delete_result)

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

                error_calls = [str(c) for c in mock_log.error.call_args_list]
                assert any("Failed to rollback" in call for call in error_calls)

    async def test_unexpected_error_cleans_up_everything(
        self,
        mock_support_collection,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """An unexpected (non-HTTP) error triggers full cleanup of files and DB."""
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = REQUEST_ID
        mock_support_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 1
        mock_support_collection.delete_one = AsyncMock(return_value=mock_delete_result)

        attachments = [
            _make_upload_file("img1.png", "image/png", b"data"),
        ]

        # Make email notification succeed, but the response construction fail
        with patch(
            "app.services.support_service._send_support_email_notifications",
            new_callable=AsyncMock,
        ):
            with patch(
                "app.services.support_service.SupportRequestResponse",
                side_effect=RuntimeError("unexpected model error"),
            ):
                with patch(
                    "app.services.support_service._delete_uploaded_files",
                    new_callable=AsyncMock,
                ) as mock_delete_files:
                    with patch("app.services.support_service.log"):
                        with pytest.raises(HTTPException) as exc_info:
                            await create_support_request_with_attachments(
                                request_data=sample_request_data,
                                attachments=attachments,
                                user_id=USER_ID,
                                user_email=USER_EMAIL,
                            )

        assert exc_info.value.status_code == 500
        mock_delete_files.assert_awaited_once()
        mock_support_collection.delete_one.assert_awaited_once()

    async def test_unexpected_error_cleanup_failures_still_raises_500(
        self,
        mock_support_collection,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """Even when both file cleanup and DB rollback fail, 500 is raised."""
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = REQUEST_ID
        mock_support_collection.insert_one = AsyncMock(return_value=mock_insert_result)

        mock_support_collection.delete_one = AsyncMock(side_effect=Exception("DB gone"))

        attachments = [
            _make_upload_file("img1.png", "image/png", b"data"),
        ]

        with patch(
            "app.services.support_service._send_support_email_notifications",
            new_callable=AsyncMock,
        ):
            with patch(
                "app.services.support_service.SupportRequestResponse",
                side_effect=RuntimeError("unexpected"),
            ):
                with patch(
                    "app.services.support_service._delete_uploaded_files",
                    new_callable=AsyncMock,
                    side_effect=Exception("cleanup gone"),
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


# ===========================================================================
# _send_support_email_notifications
# ===========================================================================


@pytest.mark.unit
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
            created_at=datetime.now(timezone.utc),
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


@pytest.mark.unit
class TestGetUserSupportRequests:
    def _setup_cursor(self, mock_collection, docs):
        """Configure the chained find().sort().skip().limit().to_list() mock."""
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=docs)
        mock_collection.find.return_value = mock_cursor
        return mock_cursor

    async def test_success_returns_requests_and_pagination(
        self,
        mock_support_collection,
    ):
        """Returns correctly formatted response with pagination."""
        doc = _make_db_support_doc()
        self._setup_cursor(mock_support_collection, [doc])
        mock_support_collection.count_documents = AsyncMock(return_value=1)

        with patch("app.services.support_service.log"):
            result = await get_user_support_requests(
                user_id=USER_ID, page=1, per_page=10
            )

        assert len(result["requests"]) == 1
        assert isinstance(result["requests"][0], SupportRequestResponse)
        assert result["pagination"]["page"] == 1
        assert result["pagination"]["per_page"] == 10
        assert result["pagination"]["total"] == 1
        assert result["pagination"]["pages"] == 1

    async def test_with_status_filter(self, mock_support_collection):
        """Status filter is applied to the query."""
        self._setup_cursor(mock_support_collection, [])
        mock_support_collection.count_documents = AsyncMock(return_value=0)

        with patch("app.services.support_service.log"):
            result = await get_user_support_requests(
                user_id=USER_ID,
                page=1,
                per_page=10,
                status_filter=SupportRequestStatus.RESOLVED,
            )

        # Verify query includes both user_id and status
        call_args = mock_support_collection.count_documents.call_args[0][0]
        assert call_args["user_id"] == USER_ID
        assert call_args["status"] == "resolved"
        assert result["requests"] == []

    async def test_empty_results(self, mock_support_collection):
        """No matching documents returns empty list."""
        self._setup_cursor(mock_support_collection, [])
        mock_support_collection.count_documents = AsyncMock(return_value=0)

        with patch("app.services.support_service.log"):
            result = await get_user_support_requests(
                user_id=USER_ID, page=1, per_page=10
            )

        assert result["requests"] == []
        assert result["pagination"]["total"] == 0
        assert result["pagination"]["pages"] == 0

    async def test_pagination_calculation(self, mock_support_collection):
        """Pagination pages are calculated correctly with ceiling division."""
        self._setup_cursor(mock_support_collection, [])
        mock_support_collection.count_documents = AsyncMock(return_value=25)

        with patch("app.services.support_service.log"):
            result = await get_user_support_requests(
                user_id=USER_ID, page=2, per_page=10
            )

        assert result["pagination"]["pages"] == 3
        assert result["pagination"]["page"] == 2

    async def test_pagination_skip_value(self, mock_support_collection):
        """The cursor uses the correct skip value for page 3."""
        mock_cursor = self._setup_cursor(mock_support_collection, [])
        mock_support_collection.count_documents = AsyncMock(return_value=50)

        with patch("app.services.support_service.log"):
            await get_user_support_requests(user_id=USER_ID, page=3, per_page=10)

        mock_cursor.skip.assert_called_once_with(20)
        mock_cursor.limit.assert_called_once_with(10)

    async def test_db_error_raises_500(self, mock_support_collection):
        """Database error raises 500."""
        mock_support_collection.count_documents = AsyncMock(
            side_effect=Exception("DB error")
        )

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await get_user_support_requests(user_id=USER_ID)

        assert exc_info.value.status_code == 500

    async def test_multiple_documents_returned(self, mock_support_collection):
        """Multiple documents are all converted to response models."""
        docs = [
            _make_db_support_doc(request_id=f"id-{i}", ticket_id=f"T-{i}")
            for i in range(3)
        ]
        self._setup_cursor(mock_support_collection, docs)
        mock_support_collection.count_documents = AsyncMock(return_value=3)

        with patch("app.services.support_service.log"):
            result = await get_user_support_requests(
                user_id=USER_ID, page=1, per_page=10
            )

        assert len(result["requests"]) == 3
        for req in result["requests"]:
            assert isinstance(req, SupportRequestResponse)


# ===========================================================================
# get_all_support_requests
# ===========================================================================


@pytest.mark.unit
class TestGetAllSupportRequests:
    def _setup_cursor(self, mock_collection, docs):
        """Configure the chained find().sort().skip().limit().to_list() mock."""
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=docs)
        mock_collection.find.return_value = mock_cursor
        return mock_cursor

    async def test_success_no_filters(self, mock_support_collection):
        """Returns all requests without filters."""
        doc = _make_db_support_doc()
        self._setup_cursor(mock_support_collection, [doc])
        mock_support_collection.count_documents = AsyncMock(return_value=1)

        with patch("app.services.support_service.log"):
            result = await get_all_support_requests(page=1, per_page=20)

        assert len(result["requests"]) == 1
        assert result["pagination"]["per_page"] == 20

        # Verify empty query (no filters)
        call_args = mock_support_collection.count_documents.call_args[0][0]
        assert call_args == {}

    async def test_with_status_filter(self, mock_support_collection):
        """Status filter is included in the query."""
        self._setup_cursor(mock_support_collection, [])
        mock_support_collection.count_documents = AsyncMock(return_value=0)

        with patch("app.services.support_service.log"):
            await get_all_support_requests(
                status_filter=SupportRequestStatus.IN_PROGRESS,
            )

        call_args = mock_support_collection.count_documents.call_args[0][0]
        assert call_args["status"] == "in_progress"

    async def test_with_type_filter(self, mock_support_collection):
        """Type filter is included in the query."""
        self._setup_cursor(mock_support_collection, [])
        mock_support_collection.count_documents = AsyncMock(return_value=0)

        with patch("app.services.support_service.log"):
            await get_all_support_requests(
                type_filter=SupportRequestType.FEATURE,
            )

        call_args = mock_support_collection.count_documents.call_args[0][0]
        assert call_args["type"] == "feature"

    async def test_with_both_filters(self, mock_support_collection):
        """Both status and type filters are applied together."""
        self._setup_cursor(mock_support_collection, [])
        mock_support_collection.count_documents = AsyncMock(return_value=0)

        with patch("app.services.support_service.log"):
            await get_all_support_requests(
                status_filter=SupportRequestStatus.OPEN,
                type_filter=SupportRequestType.SUPPORT,
            )

        call_args = mock_support_collection.count_documents.call_args[0][0]
        assert call_args["status"] == "open"
        assert call_args["type"] == "support"

    async def test_empty_results(self, mock_support_collection):
        """No documents returns empty list with zero pagination."""
        self._setup_cursor(mock_support_collection, [])
        mock_support_collection.count_documents = AsyncMock(return_value=0)

        with patch("app.services.support_service.log"):
            result = await get_all_support_requests()

        assert result["requests"] == []
        assert result["pagination"]["total"] == 0
        assert result["pagination"]["pages"] == 0

    async def test_pagination_calculation(self, mock_support_collection):
        """Pagination pages are computed with ceiling division."""
        self._setup_cursor(mock_support_collection, [])
        mock_support_collection.count_documents = AsyncMock(return_value=41)

        with patch("app.services.support_service.log"):
            result = await get_all_support_requests(page=1, per_page=20)

        assert result["pagination"]["pages"] == 3
        assert result["pagination"]["total"] == 41

    async def test_pagination_skip_and_limit(self, mock_support_collection):
        """Cursor uses correct skip and limit values."""
        mock_cursor = self._setup_cursor(mock_support_collection, [])
        mock_support_collection.count_documents = AsyncMock(return_value=100)

        with patch("app.services.support_service.log"):
            await get_all_support_requests(page=4, per_page=20)

        mock_cursor.skip.assert_called_once_with(60)
        mock_cursor.limit.assert_called_once_with(20)

    async def test_db_error_raises_500(self, mock_support_collection):
        """Database error raises 500."""
        mock_support_collection.count_documents = AsyncMock(
            side_effect=Exception("DB error")
        )

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await get_all_support_requests()

        assert exc_info.value.status_code == 500

    async def test_sort_order_is_descending_by_created_at(
        self, mock_support_collection
    ):
        """Results are sorted by created_at in descending order."""
        mock_cursor = self._setup_cursor(mock_support_collection, [])
        mock_support_collection.count_documents = AsyncMock(return_value=0)

        with patch("app.services.support_service.log"):
            await get_all_support_requests()

        mock_cursor.sort.assert_called_once_with("created_at", -1)
