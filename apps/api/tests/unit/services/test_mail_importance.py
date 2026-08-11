"""Unit tests for app/services/mail/email_importance_service.py.

The service delegates to ``mail_repository`` (real DB behaviour is covered by
the MailRepository contract tests). These tests mock the repository and assert
the service builds the response models exactly: JSON-safe dicts with string
``_id`` and no ``id`` key, exact counts/IDs, exact repository call args, and
exact log calls — so a mutation in any of them is observable.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.models.mail_models import MailDocument

MODULE = "app.services.mail.email_importance_service"

EMAIL_ID = "507f1f77bcf86cd799439011"


def _make_email(
    message_id: str = "msg-1",
    user_id: str = "user-1",
    is_important: bool = True,
    with_analyzed: bool = True,
) -> MailDocument:
    data: dict[str, object] = {
        "id": EMAIL_ID,
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
    with patch(f"{MODULE}.log") as log:
        yield log


@pytest.fixture
def mock_repo():
    with patch(f"{MODULE}.mail_repository") as repo:
        repo.list_for_user = AsyncMock(return_value=[])
        repo.get_by_message = AsyncMock(return_value=None)
        repo.list_by_message_ids = AsyncMock(return_value=[])
        yield repo


def _assert_mail_dict(email: dict[str, object], message_id: str = "msg-1") -> None:
    """Pin the exact JSON-safe shape ``_mail_dict`` must produce."""
    assert email["_id"] == EMAIL_ID
    assert "id" not in email  # excluded from model_dump, replaced by _id
    assert email["message_id"] == message_id
    assert email["user_id"] == "user-1"
    assert email["is_important"] is True
    assert email["subject"] == "Test email"  # extra field preserved
    assert email["analyzed_at"] == "2024-01-15T10:00:00Z"  # mode="json"


class TestGetEmailImportanceSummaries:
    async def test_returns_all_emails(self, mock_repo, _patch_log) -> None:
        mock_repo.list_for_user.return_value = [_make_email("msg-1"), _make_email("msg-2")]
        from app.services.mail.email_importance_service import get_email_importance_summaries

        result = await get_email_importance_summaries("user-1", limit=50)

        assert result.status == "success"
        assert result.count == 2
        assert result.filtered_by_importance is False
        _assert_mail_dict(result.emails[0], message_id="msg-1")
        _assert_mail_dict(result.emails[1], message_id="msg-2")
        # Exact log calls and repository call.
        _patch_log.set.assert_called_once_with(
            user={"id": "user-1"}, mail={"operation": "summarize"}
        )
        _patch_log.set_ns.assert_called_once_with("mail", result_count=2, success=True)
        mock_repo.list_for_user.assert_awaited_once_with(
            "user-1", important_only=False, limit=50
        )

    async def test_important_only_filter(self, mock_repo, _patch_log) -> None:
        mock_repo.list_for_user.return_value = [_make_email("msg-1", is_important=True)]
        from app.services.mail.email_importance_service import get_email_importance_summaries

        result = await get_email_importance_summaries("user-1", important_only=True)

        assert result.filtered_by_importance is True
        assert mock_repo.list_for_user.await_args.kwargs["important_only"] is True
        assert mock_repo.list_for_user.await_args.kwargs["limit"] == 50
        _patch_log.set_ns.assert_called_once_with("mail", result_count=1, success=True)

    async def test_defaults_passed_to_repository(self, mock_repo) -> None:
        from app.services.mail.email_importance_service import get_email_importance_summaries

        result = await get_email_importance_summaries("user-1")

        assert result.count == 0
        assert mock_repo.list_for_user.await_args.kwargs == {
            "important_only": False,
            "limit": 50,
        }

    async def test_error_propagates(self, mock_repo, _patch_log) -> None:
        mock_repo.list_for_user.side_effect = RuntimeError("db error")
        from app.services.mail.email_importance_service import get_email_importance_summaries

        with pytest.raises(RuntimeError, match="db error"):
            await get_email_importance_summaries("user-1")

        _patch_log.error.assert_called_once_with(
            f"{LogTag.MAIL} Error retrieving email summaries for user",
            user_id="user-1",
            error="db error",
            error_type="RuntimeError",
        )

    async def test_no_analyzed_at_is_none(self, mock_repo) -> None:
        mock_repo.list_for_user.return_value = [_make_email("msg-1", with_analyzed=False)]
        from app.services.mail.email_importance_service import get_email_importance_summaries

        result = await get_email_importance_summaries("user-1")
        assert result.count == 1
        assert result.emails[0]["analyzed_at"] is None


class TestGetSingleEmailImportanceSummary:
    async def test_email_found(self, mock_repo, _patch_log) -> None:
        mock_repo.get_by_message.return_value = _make_email("msg-1")
        from app.services.mail.email_importance_service import get_single_email_importance_summary

        result = await get_single_email_importance_summary("user-1", "msg-1")

        assert result is not None and result.status == "success"
        _assert_mail_dict(result.email)
        mock_repo.get_by_message.assert_awaited_once_with("user-1", "msg-1")
        _patch_log.set.assert_called_once_with(
            user={"id": "user-1"}, mail={"operation": "summarize"}
        )
        _patch_log.set_ns.assert_called_once_with("mail", result_count=1, success=True)

    async def test_email_not_found(self, mock_repo, _patch_log) -> None:
        mock_repo.get_by_message.return_value = None
        from app.services.mail.email_importance_service import get_single_email_importance_summary

        assert await get_single_email_importance_summary("user-1", "msg-999") is None

        mock_repo.get_by_message.assert_awaited_once_with("user-1", "msg-999")
        _patch_log.set_ns.assert_called_once_with("mail", result_count=0, success=True)

    async def test_error_propagates(self, mock_repo, _patch_log) -> None:
        mock_repo.get_by_message.side_effect = RuntimeError("db error")
        from app.services.mail.email_importance_service import get_single_email_importance_summary

        with pytest.raises(RuntimeError, match="db error"):
            await get_single_email_importance_summary("user-1", "msg-1")

        _patch_log.error.assert_called_once_with(
            f"{LogTag.MAIL} Error retrieving email summary",
            user_id="user-1",
            message_id="msg-1",
            error="db error",
            error_type="RuntimeError",
        )


class TestGetBulkEmailImportanceSummaries:
    async def test_all_found(self, mock_repo, _patch_log) -> None:
        mock_repo.list_by_message_ids.return_value = [_make_email("msg-1"), _make_email("msg-2")]
        from app.services.mail.email_importance_service import get_bulk_email_importance_summaries

        result = await get_bulk_email_importance_summaries("user-1", ["msg-1", "msg-2"])

        assert result.status == "success"
        assert set(result.emails) == {"msg-1", "msg-2"}
        _assert_mail_dict(result.emails["msg-1"], message_id="msg-1")
        _assert_mail_dict(result.emails["msg-2"], message_id="msg-2")
        assert result.found_count == 2
        assert result.missing_count == 0
        assert sorted(result.found_message_ids) == ["msg-1", "msg-2"]
        assert result.missing_message_ids == []
        _patch_log.set.assert_called_once_with(
            user={"id": "user-1"},
            mail={"operation": "summarize", "message_count": 2},
        )
        _patch_log.set_ns.assert_called_once_with("mail", result_count=2, success=True)
        mock_repo.list_by_message_ids.assert_awaited_once_with("user-1", ["msg-1", "msg-2"])

    async def test_partial_match(self, mock_repo, _patch_log) -> None:
        mock_repo.list_by_message_ids.return_value = [_make_email("msg-1")]
        from app.services.mail.email_importance_service import get_bulk_email_importance_summaries

        result = await get_bulk_email_importance_summaries("user-1", ["msg-1", "msg-2"])

        assert set(result.emails) == {"msg-1"}
        assert result.found_count == 1
        assert result.missing_count == 1
        assert result.found_message_ids == ["msg-1"]
        assert result.missing_message_ids == ["msg-2"]
        _patch_log.set_ns.assert_called_once_with("mail", result_count=1, success=True)

    async def test_duplicate_message_ids_deduped(self, mock_repo) -> None:
        mock_repo.list_by_message_ids.return_value = [_make_email("msg-1")]
        from app.services.mail.email_importance_service import get_bulk_email_importance_summaries

        result = await get_bulk_email_importance_summaries("user-1", ["msg-1", "msg-2", "msg-2"])

        assert result.found_count == 1
        assert result.missing_count == 1
        assert result.found_message_ids == ["msg-1"]
        assert result.missing_message_ids == ["msg-2"]  # deduped set semantics

    async def test_empty_message_ids(self, mock_repo, _patch_log) -> None:
        from app.services.mail.email_importance_service import get_bulk_email_importance_summaries

        result = await get_bulk_email_importance_summaries("user-1", [])

        assert result.emails == {}
        assert result.found_count == 0
        assert result.missing_count == 0
        assert result.found_message_ids == []
        assert result.missing_message_ids == []
        mock_repo.list_by_message_ids.assert_awaited_once_with("user-1", [])
        _patch_log.set.assert_called_once_with(
            user={"id": "user-1"},
            mail={"operation": "summarize", "message_count": 0},
        )
        _patch_log.set_ns.assert_called_once_with("mail", result_count=0, success=True)

    async def test_error_propagates(self, mock_repo, _patch_log) -> None:
        mock_repo.list_by_message_ids.side_effect = RuntimeError("db error")
        from app.services.mail.email_importance_service import get_bulk_email_importance_summaries

        with pytest.raises(RuntimeError, match="db error"):
            await get_bulk_email_importance_summaries("user-1", ["msg-1"])

        _patch_log.error.assert_called_once_with(
            f"{LogTag.MAIL} Error retrieving bulk email summaries for user",
            user_id="user-1",
            error="db error",
            error_type="RuntimeError",
        )
