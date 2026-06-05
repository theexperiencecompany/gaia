"""Unit tests for app/services/mail/email_importance_service.py.

Covers:
- get_email_importance_summaries (all emails, important only, error)
- get_single_email_importance_summary (found, not found, error)
- get_bulk_email_importance_summaries (found, partial match, error)
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MODULE = "app.services.mail.email_importance_service"


def _make_email_doc(
    message_id: str = "msg-1",
    user_id: str = "user-1",
    is_important: bool = True,
) -> dict[str, Any]:
    return {
        "_id": MagicMock(),  # ObjectId mock
        "user_id": user_id,
        "message_id": message_id,
        "is_important": is_important,
        "analyzed_at": datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        "subject": "Test email",
    }


def _mock_cursor(docs: list[dict[str, Any]]) -> MagicMock:
    """Build a mock async cursor that supports .sort().limit().to_list()."""
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=docs)
    return cursor


@pytest.fixture(autouse=True)
def _patch_log():
    with patch(f"{MODULE}.log"):
        yield


class TestGetEmailImportanceSummaries:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_returns_all_emails(self, mock_coll: MagicMock) -> None:
        docs = [_make_email_doc("msg-1"), _make_email_doc("msg-2")]
        mock_coll.find.return_value = _mock_cursor(docs)

        from app.services.mail.email_importance_service import (
            get_email_importance_summaries,
        )

        result = await get_email_importance_summaries("user-1", limit=50)

        assert result["status"] == "success"
        assert result["count"] == 2
        assert result["filtered_by_importance"] is False
        # _id should be converted to string
        assert isinstance(result["emails"][0]["_id"], str)
        # analyzed_at should be ISO string
        assert isinstance(result["emails"][0]["analyzed_at"], str)

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_important_only_filter(self, mock_coll: MagicMock) -> None:
        docs = [_make_email_doc("msg-1", is_important=True)]
        mock_coll.find.return_value = _mock_cursor(docs)

        from app.services.mail.email_importance_service import (
            get_email_importance_summaries,
        )

        result = await get_email_importance_summaries("user-1", important_only=True)

        assert result["filtered_by_importance"] is True
        # Check that query filter included is_important
        call_args = mock_coll.find.call_args[0][0]
        assert call_args["is_important"] is True

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_error_propagates(self, mock_coll: MagicMock) -> None:
        mock_coll.find.side_effect = RuntimeError("db error")

        from app.services.mail.email_importance_service import (
            get_email_importance_summaries,
        )

        with pytest.raises(RuntimeError, match="db error"):
            await get_email_importance_summaries("user-1")

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_no_analyzed_at_field(self, mock_coll: MagicMock) -> None:
        doc = {"_id": MagicMock(), "user_id": "user-1", "message_id": "msg-1"}
        mock_coll.find.return_value = _mock_cursor([doc])

        from app.services.mail.email_importance_service import (
            get_email_importance_summaries,
        )

        result = await get_email_importance_summaries("user-1")
        assert result["count"] == 1
        assert "analyzed_at" not in result["emails"][0]


class TestGetSingleEmailImportanceSummary:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_email_found(self, mock_coll: MagicMock) -> None:
        doc = _make_email_doc("msg-1")
        mock_coll.find_one = AsyncMock(return_value=doc)

        from app.services.mail.email_importance_service import (
            get_single_email_importance_summary,
        )

        result = await get_single_email_importance_summary("user-1", "msg-1")

        assert result is not None
        assert result["status"] == "success"
        assert isinstance(result["email"]["_id"], str)

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_email_not_found(self, mock_coll: MagicMock) -> None:
        mock_coll.find_one = AsyncMock(return_value=None)

        from app.services.mail.email_importance_service import (
            get_single_email_importance_summary,
        )

        result = await get_single_email_importance_summary("user-1", "msg-999")
        assert result is None

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_error_propagates(self, mock_coll: MagicMock) -> None:
        mock_coll.find_one = AsyncMock(side_effect=RuntimeError("db error"))

        from app.services.mail.email_importance_service import (
            get_single_email_importance_summary,
        )

        with pytest.raises(RuntimeError, match="db error"):
            await get_single_email_importance_summary("user-1", "msg-1")

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_no_analyzed_at_field(self, mock_coll: MagicMock) -> None:
        doc = {"_id": MagicMock(), "user_id": "user-1", "message_id": "msg-1"}
        mock_coll.find_one = AsyncMock(return_value=doc)

        from app.services.mail.email_importance_service import (
            get_single_email_importance_summary,
        )

        result = await get_single_email_importance_summary("user-1", "msg-1")
        assert result is not None
        assert "analyzed_at" not in result["email"]


class TestGetBulkEmailImportanceSummaries:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_all_found(self, mock_coll: MagicMock) -> None:
        docs = [
            _make_email_doc("msg-1"),
            _make_email_doc("msg-2"),
        ]
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=docs)
        mock_coll.find.return_value = cursor

        from app.services.mail.email_importance_service import (
            get_bulk_email_importance_summaries,
        )

        result = await get_bulk_email_importance_summaries("user-1", ["msg-1", "msg-2"])

        assert result["status"] == "success"
        assert result["found_count"] == 2
        assert result["missing_count"] == 0

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_partial_match(self, mock_coll: MagicMock) -> None:
        docs = [_make_email_doc("msg-1")]
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=docs)
        mock_coll.find.return_value = cursor

        from app.services.mail.email_importance_service import (
            get_bulk_email_importance_summaries,
        )

        result = await get_bulk_email_importance_summaries("user-1", ["msg-1", "msg-2"])

        assert result["found_count"] == 1
        assert result["missing_count"] == 1
        assert "msg-2" in result["missing_message_ids"]

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_error_propagates(self, mock_coll: MagicMock) -> None:
        mock_coll.find.side_effect = RuntimeError("db error")

        from app.services.mail.email_importance_service import (
            get_bulk_email_importance_summaries,
        )

        with pytest.raises(RuntimeError, match="db error"):
            await get_bulk_email_importance_summaries("user-1", ["msg-1"])
