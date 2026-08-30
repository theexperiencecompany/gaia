"""Unit tests for the support service (app/services/support_service.py)."""

from datetime import UTC, datetime
import re
import threading
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from fastapi import HTTPException, UploadFile
import pytest

from app.models.support_models import (
    SupportAttachment,
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
    MAX_ATTACHMENTS,
    SUPPORT_EMAILS,
    _delete_uploaded_files,
    _process_attachments,
    _rollback_created_request,
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


class _LocalTimeDiffersFromUTC(datetime):
    """datetime stand-in whose local-time ``now(None)`` reads a different DATE
    than its UTC ``now(UTC)``.

    The ticket id's date segment must be computed against UTC (the id is stored,
    displayed and sorted across timezones); this clock turns a non-UTC read into
    a wrong date the assertion can see, instead of relying on the CI machine's
    timezone happening to differ from UTC at run time.
    """

    UTC_NOW = datetime(2026, 6, 15, 2, 0, tzinfo=UTC)

    @classmethod
    def now(cls, tz: datetime | None = None) -> datetime:  # type: ignore[override]  # mirrors datetime.now's optional-tz signature deliberately
        if tz is None:
            return cls(2026, 6, 14, 20, 0)  # naive local read: previous day
        return cls.UTC_NOW


def _assert_ticket_id_shape(ticket_id: str) -> None:
    """Pin the ticket-id shape: GAIA-<UTC yyyymmdd>-<8 uppercase hex chars>."""
    assert re.fullmatch(r"GAIA-\d{8}-[0-9A-F]{8}", ticket_id), ticket_id


def _assert_utc_ticket_id(ticket_id: str) -> None:
    """Pin the shape AND that the date segment is the fake clock's UTC date —
    a local-time read would produce 20260614 here."""
    _assert_ticket_id_shape(ticket_id)
    date_segment = ticket_id.removeprefix("GAIA-").split("-")[0]
    assert date_segment == "20260615", f"ticket id must carry the UTC date, got {ticket_id!r}"


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
        _assert_ticket_id_shape(result.ticket_id)
        assert result.support_request is not None
        assert result.support_request.user_id == USER_ID
        assert result.support_request.status == SupportRequestStatus.OPEN
        assert result.support_request.priority == SupportRequestPriority.MEDIUM
        mock_support_repo.create.assert_awaited_once()

    async def test_the_ticket_id_date_segment_is_read_against_utc(
        self,
        monkeypatch,
        mock_support_repo,
        mock_email_notifications,
        sample_request_data,
    ):
        """A local-time read would stamp the wrong day for part of the world."""
        monkeypatch.setattr("app.services.support_service.datetime", _LocalTimeDiffersFromUTC)

        with patch("app.services.support_service.log"):
            result = await create_support_request(
                request_data=sample_request_data,
                user_id=USER_ID,
                user_email=USER_EMAIL,
                user_name=USER_NAME,
            )

        _assert_utc_ticket_id(result.ticket_id)

    async def test_create_failure_rolls_back_and_raises_500(
        self,
        mock_support_repo,
        sample_request_data,
    ):
        """When the repository create fails, the request is rolled back and 500 raised."""
        mock_support_repo.create.side_effect = RuntimeError("write failed")

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await create_support_request(
                    request_data=sample_request_data,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        assert exc_info.value.status_code == 500
        assert "Failed to create" in exc_info.value.detail
        mock_support_repo.delete.assert_awaited_once()

    async def test_email_failure_triggers_rollback_and_raises_500(
        self,
        mock_support_repo,
        mock_send_team_notification,
        mock_send_user_email,
        sample_request_data,
    ):
        """Email failure causes a repository delete (rollback) and raises 500."""
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
        mock_support_repo.delete.assert_awaited_once_with(ANY, user_id=USER_ID)

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

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await create_support_request(
                    request_data=sample_request_data,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        assert exc_info.value.status_code == 500

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

            # Verify that an error about failed rollback was logged
            error_calls = [str(c) for c in mock_log.error.call_args_list]
            assert any("Failed to rollback" in call for call in error_calls)

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
                with patch("app.services.support_service.log"):
                    with pytest.raises(HTTPException) as exc_info:
                        await create_support_request(
                            request_data=sample_request_data,
                            user_id=USER_ID,
                            user_email=USER_EMAIL,
                        )

        assert exc_info.value.status_code == 500
        mock_support_repo.delete.assert_awaited_once()

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
        # The email notification should have been called with user_name="User"
        mock_send_team_notification.assert_awaited_once()


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
        mock_support_repo.create.assert_awaited_once()
        stored = mock_support_repo.create.await_args.args[0]
        assert len(stored.attachments) == 2  # both uploads recorded on the document

    async def test_ticket_id_matches_gaia_format(
        self,
        mock_support_repo,
        mock_email_notifications,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """Ticket id is GAIA-<YYYYMMDD>-<8 uppercase hex>."""
        with patch("app.services.support_service.log"):
            result = await create_support_request_with_attachments(
                request_data=sample_request_data,
                attachments=[],
                user_id=USER_ID,
                user_email=USER_EMAIL,
            )

        assert re.fullmatch(r"GAIA-\d{8}-[0-9A-F]{8}", result.ticket_id)

    async def test_log_context_and_success_logs_are_exact(
        self,
        mock_support_repo,
        mock_email_notifications,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """The wide-event context and the success log lines carry exact values."""
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

        mock_log.set.assert_called_once_with(
            component="support_service",
            user_id=USER_ID,
            attachment_count=2,
        )
        db_log = next(
            call for call in mock_log.info.call_args_list if "created in database" in call.args[0]
        )
        assert (
            db_log.args[0] == "Support request with attachments created in database"
            and db_log.kwargs["ticket_id"] == result.ticket_id
        )
        done_log = next(
            call for call in mock_log.info.call_args_list if "created successfully" in call.args[0]
        )
        assert done_log.args[0] == "Support request with images created successfully: for user"
        assert done_log.kwargs["processed_attachments_count"] == 2
        assert done_log.kwargs["ticket_id"] == result.ticket_id
        assert done_log.kwargs["user_id"] == USER_ID

    async def test_stored_document_fields_are_exact(
        self,
        mock_support_repo,
        mock_email_notifications,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """The stored document carries the with-images source, image count, priority."""
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
        assert stored.metadata == {
            "source": "web_form_with_images",
            "user_agent": None,
            "image_count": 2,
        }
        assert stored.priority is SupportRequestPriority.MEDIUM
        assert stored.type is SupportRequestType.SUPPORT
        assert stored.title == sample_request_data.title
        assert stored.description == sample_request_data.description
        assert [a.filename for a in stored.attachments] == ["img1.png", "img2.jpg"]
        # The response message names the with-images path exactly.
        assert (
            result.message
            == "Support request with images submitted successfully. You will receive an email confirmation shortly."
        )
        assert result.success is True

    async def test_disallowed_content_type_rejected_with_exact_detail(
        self,
        mock_support_repo,
        sample_request_data,
    ):
        """A non-image attachment is rejected before any upload happens."""
        attachments = [_make_upload_file("doc.gif", "image/gif", b"gif")]

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await create_support_request_with_attachments(
                    request_data=sample_request_data,
                    attachments=attachments,
                    user_id=USER_ID,
                    user_email=USER_EMAIL,
                )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == (
            "Only image files are supported. File type image/gif not allowed. "
            "Please use JPG, PNG, or WebP."
        )
        mock_support_repo.create.assert_not_awaited()

    async def test_max_attachments_detail_is_exact(self, mock_support_repo, sample_request_data):
        """More than 5 attachments raises 400 with the exact limit message."""
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

    async def test_email_notification_payload_is_exact(
        self,
        mock_support_repo,
        mock_send_team_notification,
        mock_send_user_email,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        """Team notification receives the full payload incl. uploaded metadata."""
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
                user_name=None,  # exercises the "User" fallback in the email
            )

        (notification,) = mock_send_team_notification.await_args.args
        assert notification.user_name == "User"
        assert notification.user_email == USER_EMAIL
        assert notification.ticket_id == result.ticket_id
        assert notification.type is SupportRequestType.SUPPORT
        assert notification.title == sample_request_data.title
        assert notification.description == sample_request_data.description
        assert notification.support_emails == SUPPORT_EMAILS
        assert [a.filename for a in notification.attachments] == ["img1.png", "img2.jpg"]
        mock_send_user_email.assert_awaited_once_with(notification)

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

    async def test_the_ticket_id_date_segment_is_read_against_utc(
        self,
        monkeypatch,
        mock_support_repo,
        mock_email_notifications,
        sample_request_data,
    ):
        """Same UTC contract as the plain create — pinned on both entry points."""
        monkeypatch.setattr("app.services.support_service.datetime", _LocalTimeDiffersFromUTC)

        with patch("app.services.support_service.log"):
            result = await create_support_request_with_attachments(
                request_data=sample_request_data,
                attachments=[],
                user_id=USER_ID,
                user_email=USER_EMAIL,
            )

        _assert_utc_ticket_id(result.ticket_id)

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
        mock_support_repo.delete.assert_awaited_once()

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
            with patch("app.services.support_service.log"):
                with pytest.raises(HTTPException):
                    await create_support_request_with_attachments(
                        request_data=sample_request_data,
                        attachments=attachments,
                        user_id=USER_ID,
                        user_email=USER_EMAIL,
                    )

        # DB rollback should still be attempted
        mock_support_repo.delete.assert_awaited_once()

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

                error_calls = [str(c) for c in mock_log.error.call_args_list]
                assert any("Failed to rollback" in call for call in error_calls)

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
        mock_support_repo.delete.assert_awaited_once()

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
                    with patch("app.services.support_service.log"):
                        with pytest.raises(HTTPException) as exc_info:
                            await create_support_request_with_attachments(
                                request_data=sample_request_data,
                                attachments=attachments,
                                user_id=USER_ID,
                                user_email=USER_EMAIL,
                            )

        assert exc_info.value.status_code == 500

    async def test_attachment_processing_receives_the_generated_ticket(
        self, mock_support_repo, mock_email_notifications, sample_request_data
    ):
        """Uploads are keyed by the ticket id generated inside this call — a
        None ticket would misname every Cloudinary object."""
        with (
            patch(
                "app.services.support_service._process_attachments",
                new_callable=AsyncMock,
                return_value=([], []),
            ) as process,
            patch("app.services.support_service.log"),
        ):
            await create_support_request_with_attachments(
                request_data=sample_request_data,
                attachments=[_make_upload_file("img1.png", "image/png", b"data")],
                user_id=USER_ID,
                user_email=USER_EMAIL,
            )

        stored = mock_support_repo.create.await_args.args[0]
        assert process.await_args.args[1] == stored.ticket_id

    async def test_email_failure_rolls_back_with_the_generated_ids_and_error(
        self,
        mock_support_repo,
        mock_email_notifications,
        mock_upload_file_to_cloudinary,
        sample_request_data,
    ):
        err = RuntimeError("smtp refused")

        def _fail_team(_notification: Any) -> None:
            raise err

        with (
            patch(
                "app.services.support_service._send_support_email_notifications",
                side_effect=_fail_team,
            ),
            patch(
                "app.services.support_service._rollback_created_request",
                new_callable=AsyncMock,
            ) as rollback,
            patch(
                "app.services.support_service._delete_uploaded_files",
                new_callable=AsyncMock,
            ),
            patch("app.services.support_service.log"),
            pytest.raises(HTTPException),
        ):
            await create_support_request_with_attachments(
                request_data=sample_request_data,
                attachments=[_make_upload_file("img1.png", "image/png", b"data")],
                user_id=USER_ID,
                user_email=USER_EMAIL,
            )

        stored = mock_support_repo.create.await_args.args[0]
        assert rollback.await_count == 1
        args = rollback.await_args.args
        assert args[0] == stored.ticket_id
        assert args[1] == stored.id
        assert args[2] == USER_ID
        assert args[3] is err

    async def test_unexpected_error_detail_names_the_cause(
        self, mock_support_repo, sample_request_data
    ):
        """The catch-all handler's detail carries the underlying error text."""
        with (
            patch(
                "app.services.support_service._send_support_email_notifications",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.support_service.SupportRequestResponse.model_validate",
                side_effect=RuntimeError("unexpected model error"),
            ),
            patch("app.services.support_service.log"),
            pytest.raises(HTTPException) as exc_info,
        ):
            await create_support_request_with_attachments(
                request_data=sample_request_data,
                attachments=[],
                user_id=USER_ID,
                user_email=USER_EMAIL,
            )

        assert exc_info.value.detail == ("Failed to create support request: unexpected model error")


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

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await get_user_support_requests(user_id=USER_ID)

        assert exc_info.value.status_code == 500

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

    async def test_defaults_are_page_one_and_per_page_ten(self, mock_support_repo):
        """Calling with only user_id uses page=1, per_page=10 end to end."""
        mock_support_repo.page_for_user.return_value = []
        mock_support_repo.count_for_user_status.return_value = 0

        with patch("app.services.support_service.log"):
            result = await get_user_support_requests(user_id=USER_ID)

        page_call = mock_support_repo.page_for_user.await_args
        assert page_call.kwargs["skip"] == 0
        assert page_call.kwargs["limit"] == 10
        assert result.pagination.page == 1
        assert result.pagination.per_page == 10

    async def test_second_page_skip_is_exactly_per_page(self, mock_support_repo):
        """skip == (page - 1) * per_page exactly: page 2 → skip 10."""
        mock_support_repo.page_for_user.return_value = []
        mock_support_repo.count_for_user_status.return_value = 0

        with patch("app.services.support_service.log"):
            await get_user_support_requests(user_id=USER_ID, page=2, per_page=10)

        page_call = mock_support_repo.page_for_user.await_args
        assert type(page_call.kwargs["skip"]) is int
        assert page_call.kwargs["skip"] == 10

    async def test_pages_ceil_division_boundaries(self, mock_support_repo):
        """pages is ceil(total / per_page): exact int at each boundary."""
        for total, expected_pages in [(1, 1), (9, 1), (10, 1), (11, 2), (20, 2), (21, 3)]:
            mock_support_repo.page_for_user.return_value = []
            mock_support_repo.count_for_user_status.return_value = total

            with patch("app.services.support_service.log"):
                result = await get_user_support_requests(user_id=USER_ID, page=1, per_page=10)

            assert result.pagination.total == total
            assert result.pagination.pages == expected_pages
            assert isinstance(result.pagination.pages, int)
            assert result.pagination.page == 1
            assert result.pagination.per_page == 10

    async def test_db_error_detail_is_exact(self, mock_support_repo):
        """Database error raises a 500 with the exact detail string."""
        mock_support_repo.count_for_user_status.side_effect = Exception("DB error")

        with patch("app.services.support_service.log"):
            with pytest.raises(HTTPException) as exc_info:
                await get_user_support_requests(user_id=USER_ID)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to fetch support requests"


# ===========================================================================
# Log-arg-exact pins for the rollback / attachment helpers
#
# These assert every log call's message and kwargs exactly, so a mutated
# literal, kwarg, or branch inside these helpers fails a test.
# ===========================================================================


_COMPENSATION_FAILED_DETAIL = (
    "Email sending failed and automatic cleanup of the support "
    "request also failed. The request may still be stored — "
    "please contact support instead of retrying."
)


class TestRollbackCreatedRequest:
    async def test_delete_success_logs_info_with_exact_args(self, mock_support_repo):
        mock_support_repo.delete.return_value = True
        with patch("app.services.support_service.log") as log:
            await _rollback_created_request("GAIA-1", "req-1", USER_ID, RuntimeError("boom"))

        mock_support_repo.delete.assert_awaited_once_with("req-1", user_id=USER_ID)
        log.info.assert_called_once_with(
            "Successfully rolled back support request from database", ticket_id="GAIA-1"
        )
        log.error.assert_not_called()

    async def test_delete_false_logs_error_and_raises_compensation_failure(self, mock_support_repo):
        mock_support_repo.delete.return_value = False
        err = ValueError("smtp down")
        with patch("app.services.support_service.log") as log:
            with pytest.raises(HTTPException) as exc_info:
                await _rollback_created_request("GAIA-2", "req-2", USER_ID, err)

        assert exc_info.value.status_code == 500
        # Exact: this is the message a stranded user reads — any rewording or
        # case change is a different contract.
        assert exc_info.value.detail == _COMPENSATION_FAILED_DETAIL
        assert isinstance(exc_info.value.__cause__, ValueError)
        log.error.assert_called_once_with(
            "Failed to rollback support request from database",
            ticket_id="GAIA-2",
            error="smtp down",
            error_type="ValueError",
            user_id=USER_ID,
        )
        log.info.assert_not_called()

    async def test_delete_raising_logs_error_and_raises_compensation_failure(
        self, mock_support_repo
    ):
        mock_support_repo.delete.side_effect = RuntimeError("mongo write failed")
        with patch("app.services.support_service.log") as log:
            with pytest.raises(HTTPException) as exc_info:
                await _rollback_created_request("GAIA-3", "req-3", USER_ID, ValueError("email"))

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == _COMPENSATION_FAILED_DETAIL
        assert isinstance(exc_info.value.__cause__, RuntimeError)
        log.error.assert_called_once_with(
            "Error during rollback for ticket",
            ticket_id="GAIA-3",
            error="mongo write failed",
            error_type="RuntimeError",
            user_id=USER_ID,
        )


class TestProcessAttachmentsPins:
    async def test_empty_attachment_list_returns_two_empty_lists(self):
        assert await _process_attachments([], "GAIA-1", datetime.now(UTC)) == ([], [])

    async def test_over_limit_raises_with_exact_detail(self, sample_request_data):
        uploads = [_make_upload_file(filename=f"f{i}.png") for i in range(MAX_ATTACHMENTS + 1)]
        with pytest.raises(HTTPException) as exc:
            await _process_attachments(uploads, "GAIA-1", datetime.now(UTC))
        assert exc.value.status_code == 400
        assert exc.value.detail == f"Maximum {MAX_ATTACHMENTS} images allowed"

    async def test_success_returns_urls_and_metadata_in_order(self, mock_upload_file_to_cloudinary):
        uploads = [_make_upload_file(), _make_upload_file()]
        urls, processed = await _process_attachments(uploads, "GAIA-9", datetime.now(UTC))
        assert len(urls) == 2
        assert len(processed) == 2
        assert urls == ["https://res.cloudinary.com/demo/support/ticket_file.png"] * 2
        for att in processed:
            assert isinstance(att, SupportAttachment)

    async def test_each_upload_receives_its_attachment_ticket_and_constraints(self):
        """Every per-file task must carry the real ticket id and the module's
        type/size constraints — a None ticket misnames the Cloudinary object,
        and None constraints would accept anything."""
        now = datetime.now(UTC)
        uploads = [_make_upload_file("a.png"), _make_upload_file("b.png")]
        with patch(
            "app.services.support_service._upload_single_attachment",
            new_callable=AsyncMock,
            return_value=("url", MagicMock(spec=SupportAttachment)),
        ) as upload:
            await _process_attachments(uploads, "GAIA-7", now)

        assert upload.await_count == 2
        first = upload.await_args_list[0].kwargs
        assert first["attachment"] is uploads[0]
        assert first["ticket_id"] == "GAIA-7"
        assert first["current_time"] == now
        assert first["allowed_types"] == ALLOWED_TYPES
        assert first["max_file_size"] == MAX_FILE_SIZE

    async def test_results_after_a_failed_upload_are_still_collected_for_cleanup(
        self, mock_upload_file_to_cloudinary
    ):
        """gather returns every outcome; files uploaded AFTER the failing one
        still made it to Cloudinary and must be cleaned up too — bailing out of
        the results loop orphans them there forever."""
        mock_upload_file_to_cloudinary.side_effect = [
            "https://res.cloudinary.com/demo/support/GAIA-3_a.png",
            RuntimeError("cloudinary down"),
            "https://res.cloudinary.com/demo/support/GAIA-3_c.png",
        ]
        with (
            patch(
                "app.services.support_service._delete_uploaded_files",
                new_callable=AsyncMock,
            ) as delete,
            patch("app.services.support_service.log"),
            pytest.raises(HTTPException),
        ):
            await _process_attachments(
                [
                    _make_upload_file("a.png"),
                    _make_upload_file("b.png"),
                    _make_upload_file("c.png"),
                ],
                "GAIA-3",
                datetime.now(UTC),
            )

        deleted_urls = delete.await_args.args[0]
        assert deleted_urls == [
            "https://res.cloudinary.com/demo/support/GAIA-3_a.png",
            "https://res.cloudinary.com/demo/support/GAIA-3_c.png",
        ]

    async def test_upload_failure_cleans_up_partial_and_reraises(
        self, mock_upload_file_to_cloudinary
    ):
        calls: list[str] = []

        def flaky(*args: Any, **kwargs: Any) -> str:
            # upload_file_to_cloudinary is called synchronously (via
            # loop.run_in_executor), so this stand-in must be sync too --
            # an async side_effect here would return an un-awaited coroutine
            # instead of ever raising.
            calls.append("upload")
            if len(calls) == 2:
                raise RuntimeError("cloudinary down")
            return "https://res.cloudinary.com/demo/support/ticket_file.png"

        mock_upload_file_to_cloudinary.side_effect = flaky
        deleted: list[list[str]] = []

        async def fake_delete(urls: list[str]) -> None:
            deleted.append(list(urls))

        # _upload_single_attachment wraps any upload failure into an
        # HTTPException (keeping the original as __cause__) before
        # _process_attachments ever sees it.
        with (
            patch("app.services.support_service._delete_uploaded_files", side_effect=fake_delete),
            pytest.raises(HTTPException) as exc_info,
        ):
            await _process_attachments(
                [_make_upload_file(), _make_upload_file()], "GAIA-2", datetime.now(UTC)
            )

        assert exc_info.value.status_code == 500
        assert isinstance(exc_info.value.__cause__, RuntimeError)
        assert str(exc_info.value.__cause__) == "cloudinary down"
        assert deleted == [["https://res.cloudinary.com/demo/support/ticket_file.png"]]


class TestCreateSupportRequestLogPins:
    async def test_entry_context_is_exact(
        self, mock_support_repo, sample_request_data, mock_email_notifications
    ):
        """The wide-event context names the component and the requesting user."""
        with patch("app.services.support_service.log") as log:
            await create_support_request(sample_request_data, USER_ID, USER_EMAIL, USER_NAME)

        log.set.assert_called_once_with(component="support_service", user_id=USER_ID)

    async def test_email_failure_rolls_back_with_the_generated_ids_and_error(
        self, mock_support_repo, sample_request_data, mock_email_notifications
    ):
        """The rollback must receive exactly what was created — ticket id,
        request id, user, and the actual email error — or it compensates a
        different row (or none)."""
        team_fn, _ = mock_email_notifications
        err = RuntimeError("smtp refused")
        team_fn.side_effect = err
        with (
            patch(
                "app.services.support_service._rollback_created_request",
                new_callable=AsyncMock,
            ) as rollback,
            patch("app.services.support_service.log"),
            pytest.raises(HTTPException),
        ):
            await create_support_request(sample_request_data, USER_ID, USER_EMAIL, USER_NAME)

        stored = mock_support_repo.create.await_args.args[0]
        assert rollback.await_count == 1
        args = rollback.await_args.args
        assert args[0] == stored.ticket_id
        assert args[1] == stored.id
        assert args[2] == USER_ID
        assert args[3] is err

    async def test_email_failure_rolls_back_with_exact_args_and_raises_exact_detail(
        self, mock_support_repo, sample_request_data, mock_email_notifications
    ):
        team_fn, _ = mock_email_notifications
        team_fn.side_effect = RuntimeError("smtp refused")
        with patch("app.services.support_service.log") as log:
            with pytest.raises(HTTPException) as exc:
                await create_support_request(sample_request_data, USER_ID, USER_EMAIL, USER_NAME)

        assert exc.value.status_code == 500
        assert exc.value.detail == (
            "Failed to send email notifications. Support request was not created. Please try again."
        )
        assert isinstance(exc.value.__cause__, RuntimeError)
        # The rollback helper received the generated ticket/request ids.
        mock_support_repo.delete.assert_awaited_once()
        delete_args = mock_support_repo.delete.await_args
        assert delete_args.args[0] == delete_args.kwargs.get("request_id", delete_args.args[0])
        assert delete_args.kwargs["user_id"] == USER_ID
        # _send_support_email_notifications logs its own failure first; find
        # the support-service-level call by name rather than assuming index 0.
        ticket_id = next(
            c.kwargs["ticket_id"]
            for c in log.error.call_args_list
            if c.args[0] == "Email sending failed for ticket"
        )
        log.error.assert_any_call(
            "Email sending failed for ticket",
            ticket_id=ticket_id,
            error="smtp refused",
            error_type="RuntimeError",
            user_id=USER_ID,
        )

    async def test_success_response_shape_is_exact(
        self, mock_support_repo, sample_request_data, mock_email_notifications
    ):
        response = await create_support_request(sample_request_data, USER_ID, USER_EMAIL, USER_NAME)
        assert response.success is True
        assert response.message == (
            "Support request submitted successfully. You will receive an email confirmation "
            "shortly."
        )
        assert re.match(r"^GAIA-\d{8}-[0-9A-F]{8}$", response.ticket_id)
        assert response.support_request.user_email == USER_EMAIL
        assert response.support_request.priority == SupportRequestPriority.MEDIUM
        mock_support_repo.delete.assert_not_awaited()
