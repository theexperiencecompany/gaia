"""Unit tests for app/services/mail/email_importance_service.py.

The service now delegates to ``mail_repository`` (real DB behaviour is covered by
the MailRepository contract tests). These tests mock the repository and assert the
service shapes the JSON-safe response dicts correctly.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.mail_models import MailDocument

MODULE = "app.services.mail.email_importance_service"


def _make_email(
    message_id: str = "msg-1",
    user_id: str = "user-1",
    is_important: bool = True,
    with_analyzed: bool = True,
) -> MailDocument:
    data: dict[str, object] = {
        "id": "507f1f77bcf86cd799439011",
        "user_id": user_id,
        "message_id": message_id,
        "is_important": is_important,
        "subject": "Test email",
    }
    if with_analyzed:
        data["analyzed_at"] = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    return MailDocument.model_validate(data)


@pytest.fixture(autouse=True)
def _patch_log():
    with patch(f"{MODULE}.log"):
        yield


@pytest.fixture
def mock_repo():
    with patch(f"{MODULE}.mail_repository") as repo:
        repo.list_for_user = AsyncMock(return_value=[])
        repo.get_by_message = AsyncMock(return_value=None)
        repo.list_by_message_ids = AsyncMock(return_value=[])
        yield repo


class TestGetEmailImportanceSummaries:
    async def test_returns_all_emails(self, mock_repo) -> None:
        mock_repo.list_for_user.return_value = [_make_email("msg-1"), _make_email("msg-2")]
        from app.services.mail.email_importance_service import get_email_importance_summaries

        result = await get_email_importance_summaries("user-1", limit=50)

        assert result["status"] == "success"
        assert result["count"] == 2
        assert result["filtered_by_importance"] is False
        assert isinstance(result["emails"][0]["_id"], str)
        assert isinstance(result["emails"][0]["analyzed_at"], str)  # ISO string
        assert result["emails"][0]["subject"] == "Test email"  # extra field preserved

    async def test_important_only_filter(self, mock_repo) -> None:
        mock_repo.list_for_user.return_value = [_make_email("msg-1", is_important=True)]
        from app.services.mail.email_importance_service import get_email_importance_summaries

        result = await get_email_importance_summaries("user-1", important_only=True)

        assert result["filtered_by_importance"] is True
        assert mock_repo.list_for_user.await_args.kwargs["important_only"] is True

    async def test_error_propagates(self, mock_repo) -> None:
        mock_repo.list_for_user.side_effect = RuntimeError("db error")
        from app.services.mail.email_importance_service import get_email_importance_summaries

        with pytest.raises(RuntimeError, match="db error"):
            await get_email_importance_summaries("user-1")

    async def test_no_analyzed_at_is_none(self, mock_repo) -> None:
        mock_repo.list_for_user.return_value = [_make_email("msg-1", with_analyzed=False)]
        from app.services.mail.email_importance_service import get_email_importance_summaries

        result = await get_email_importance_summaries("user-1")
        assert result["count"] == 1
        assert result["emails"][0]["analyzed_at"] is None


class TestGetSingleEmailImportanceSummary:
    async def test_email_found(self, mock_repo) -> None:
        mock_repo.get_by_message.return_value = _make_email("msg-1")
        from app.services.mail.email_importance_service import get_single_email_importance_summary

        result = await get_single_email_importance_summary("user-1", "msg-1")

        assert result is not None and result["status"] == "success"
        assert isinstance(result["email"]["_id"], str)
        mock_repo.get_by_message.assert_awaited_once_with("user-1", "msg-1")

    async def test_email_not_found(self, mock_repo) -> None:
        mock_repo.get_by_message.return_value = None
        from app.services.mail.email_importance_service import get_single_email_importance_summary

        assert await get_single_email_importance_summary("user-1", "msg-999") is None

    async def test_error_propagates(self, mock_repo) -> None:
        mock_repo.get_by_message.side_effect = RuntimeError("db error")
        from app.services.mail.email_importance_service import get_single_email_importance_summary

        with pytest.raises(RuntimeError, match="db error"):
            await get_single_email_importance_summary("user-1", "msg-1")


class TestGetBulkEmailImportanceSummaries:
    async def test_all_found(self, mock_repo) -> None:
        mock_repo.list_by_message_ids.return_value = [_make_email("msg-1"), _make_email("msg-2")]
        from app.services.mail.email_importance_service import get_bulk_email_importance_summaries

        result = await get_bulk_email_importance_summaries("user-1", ["msg-1", "msg-2"])

        assert result["status"] == "success"
        assert result["found_count"] == 2
        assert result["missing_count"] == 0

    async def test_partial_match(self, mock_repo) -> None:
        mock_repo.list_by_message_ids.return_value = [_make_email("msg-1")]
        from app.services.mail.email_importance_service import get_bulk_email_importance_summaries

        result = await get_bulk_email_importance_summaries("user-1", ["msg-1", "msg-2"])

        assert result["found_count"] == 1
        assert result["missing_count"] == 1
        assert "msg-2" in result["missing_message_ids"]

    async def test_error_propagates(self, mock_repo) -> None:
        mock_repo.list_by_message_ids.side_effect = RuntimeError("db error")
        from app.services.mail.email_importance_service import get_bulk_email_importance_summaries

        with pytest.raises(RuntimeError, match="db error"):
            await get_bulk_email_importance_summaries("user-1", ["msg-1"])
