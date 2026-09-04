"""Tests for email attachment resolution (app/services/composio/attachments.py)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.mail_models import AttachmentReference
from app.services.composio.attachments import (
    resolve_attachments_sync,
    upload_bytes_sync,
)
from app.utils.errors import AppError

MODULE = "app.services.composio.attachments"
SERVICE = "app.services.composio.composio_service"


class TestAttachmentReferenceValidation:
    def test_accepts_exactly_one_source(self):
        assert AttachmentReference(workspace_path="a/b.pdf").workspace_path == "a/b.pdf"
        assert AttachmentReference(url="https://x/y.pdf").url == "https://x/y.pdf"

    def test_rejects_both_sources(self):
        with pytest.raises(ValueError, match="exactly one"):
            AttachmentReference(workspace_path="a", url="b")

    def test_rejects_no_source(self):
        with pytest.raises(ValueError, match="exactly one"):
            AttachmentReference(name="only-a-name.pdf")


def _fake_uploadable(name: str, mimetype: str, s3key: str) -> MagicMock:
    fu = MagicMock()
    fu.name, fu.mimetype, fu.s3key = name, mimetype, s3key
    return fu


class TestResolveAttachmentsSync:
    def test_workspace_path_uploads_via_from_path(self):
        refs = [AttachmentReference(workspace_path="/workspace/sessions/c/x.pdf")]
        svc = MagicMock()
        svc.composio.client = "CLIENT"
        with (
            patch(f"{SERVICE}.get_composio_service", return_value=svc),
            patch(f"{MODULE}.resolve_user_file_sync", return_value=Path("/mnt/jfs/x.pdf")) as res,
            patch(f"{MODULE}.FileUploadable") as fu_cls,
        ):
            fu_cls.from_path.return_value = _fake_uploadable("x.pdf", "application/pdf", "k/1")
            out = resolve_attachments_sync(
                "u1", refs, tool="GMAIL_CREATE_EMAIL_DRAFT", toolkit="gmail"
            )

        # The /workspace/ prefix is stripped before hitting the resolver.
        assert res.call_args.args == ("u1", "sessions/c/x.pdf")
        assert out == [{"name": "x.pdf", "mimetype": "application/pdf", "s3key": "k/1"}]
        # The resolved host path + the invoking tool/toolkit reach Composio, with the
        # generic path denylist/allowlist disabled (our own resolver already contained it).
        assert fu_cls.from_path.call_args.kwargs == {
            "client": "CLIENT",
            "file": "/mnt/jfs/x.pdf",
            "tool": "GMAIL_CREATE_EMAIL_DRAFT",
            "toolkit": "gmail",
            "sensitive_file_upload_protection": False,
            "file_upload_allowlist": None,
        }
        assert fu_cls.from_url.called is False  # workspace path never hits the URL branch

    def test_bare_relative_workspace_path_only_strips_leading_slash(self):
        # A path without the /workspace/ prefix keeps its segments, minus a leading /.
        refs = [AttachmentReference(workspace_path="/uploads/deck.pdf")]
        with (
            patch(f"{SERVICE}.get_composio_service", return_value=MagicMock()),
            patch(f"{MODULE}.resolve_user_file_sync", return_value=Path("/mnt/jfs/d")) as res,
            patch(f"{MODULE}.FileUploadable") as fu_cls,
        ):
            fu_cls.from_path.return_value = _fake_uploadable("deck.pdf", "application/pdf", "k/9")
            resolve_attachments_sync("u1", refs, tool="GMAIL_SEND_EMAIL", toolkit="gmail")
        assert res.call_args.args == ("u1", "uploads/deck.pdf")

    def test_url_uploads_via_from_url(self):
        refs = [AttachmentReference(url="https://drive/download/123", name="report.pdf")]
        svc = MagicMock()
        svc.composio.client = "CLIENT"
        with (
            patch(f"{SERVICE}.get_composio_service", return_value=svc),
            patch(f"{MODULE}.FileUploadable") as fu_cls,
        ):
            fu_cls.from_url.return_value = _fake_uploadable("dl", "application/pdf", "k/2")
            out = resolve_attachments_sync("u1", refs, tool="GMAIL_SEND_EMAIL", toolkit="gmail")

        # The Composio client + URL + invoking tool/toolkit reach Composio.
        assert fu_cls.from_url.call_args.kwargs["client"] == "CLIENT"
        assert fu_cls.from_url.call_args.kwargs["url"] == "https://drive/download/123"
        assert fu_cls.from_url.call_args.kwargs["tool"] == "GMAIL_SEND_EMAIL"
        assert fu_cls.from_url.call_args.kwargs["toolkit"] == "gmail"
        assert fu_cls.from_path.called is False
        # An explicit name overrides the uploaded file's own name.
        assert out == [{"name": "report.pdf", "mimetype": "application/pdf", "s3key": "k/2"}]

    def test_raises_apperror_when_upload_fails(self):
        refs = [AttachmentReference(url="https://drive/broken")]
        with (
            patch(f"{SERVICE}.get_composio_service", return_value=MagicMock()),
            patch(f"{MODULE}.FileUploadable") as fu_cls,
        ):
            fu_cls.from_url.side_effect = RuntimeError("404 not found")
            with pytest.raises(AppError) as exc:
                resolve_attachments_sync("u1", refs, tool="GMAIL_SEND_EMAIL", toolkit="gmail")
        assert exc.value.status_code == 400
        # The error names the failing source and surfaces the underlying cause,
        # and carries actionable why/fix guidance.
        assert "https://drive/broken" in exc.value.message
        assert "404 not found" in exc.value.message
        assert exc.value.why
        assert exc.value.fix

    def test_all_or_nothing_second_failure_aborts(self):
        refs = [
            AttachmentReference(url="https://ok"),
            AttachmentReference(url="https://bad"),
        ]
        with (
            patch(f"{SERVICE}.get_composio_service", return_value=MagicMock()),
            patch(f"{MODULE}.FileUploadable") as fu_cls,
        ):
            fu_cls.from_url.side_effect = [
                _fake_uploadable("ok", "text/plain", "k/ok"),
                RuntimeError("boom"),
            ]
            with pytest.raises(AppError):
                resolve_attachments_sync("u1", refs, tool="GMAIL_SEND_EMAIL", toolkit="gmail")


class TestUploadBytesSync:
    def test_uploads_bytes_and_returns_attachment(self):
        svc = MagicMock()
        svc.composio.client = "CLIENT"
        with (
            patch(f"{SERVICE}.get_composio_service", return_value=svc),
            patch(f"{MODULE}._upload_bytes_to_s3", return_value="k/3") as up,
        ):
            out = upload_bytes_sync(
                b"hello", "note.txt", "text/plain", tool="GMAIL_SEND_EMAIL", toolkit="gmail"
            )
        # Every field is threaded straight through to the Composio uploader.
        assert up.call_args.kwargs == {
            "client": "CLIENT",
            "filename": "note.txt",
            "content": b"hello",
            "mimetype": "text/plain",
            "tool": "GMAIL_SEND_EMAIL",
            "toolkit": "gmail",
        }
        assert out == {"name": "note.txt", "mimetype": "text/plain", "s3key": "k/3"}

    def test_defaults_mimetype_when_missing(self):
        with (
            patch(f"{SERVICE}.get_composio_service", return_value=MagicMock()),
            patch(f"{MODULE}._upload_bytes_to_s3", return_value="k/4"),
        ):
            out = upload_bytes_sync(b"x", "blob", None, tool="GMAIL_SEND_EMAIL", toolkit="gmail")
        assert out["mimetype"] == "application/octet-stream"
