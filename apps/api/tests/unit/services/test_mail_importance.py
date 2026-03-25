"""Unit tests for app/services/mail/email_importance_service.py.

Covers:
- get_email_importance_summaries (all emails, important only, error)
- get_single_email_importance_summary (found, not found, error)
- process_email_comprehensive_analysis (success, parse error, outer exception)
- get_bulk_email_importance_summaries (found, partial match, error)
"""

from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MODULE = "app.services.mail.email_importance_service"


def _make_email_doc(
    message_id: str = "msg-1",
    user_id: str = "user-1",
    is_important: bool = True,
) -> Dict[str, Any]:
    return {
        "_id": MagicMock(),  # ObjectId mock
        "user_id": user_id,
        "message_id": message_id,
        "is_important": is_important,
        "analyzed_at": datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        "subject": "Test email",
    }


def _mock_cursor(docs: List[Dict[str, Any]]) -> MagicMock:
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


class TestProcessEmailComprehensiveAnalysis:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.email_comprehensive_parser")
    @patch(f"{MODULE}.init_llm")
    async def test_success_with_string_response(
        self, mock_init_llm: MagicMock, mock_parser: MagicMock
    ) -> None:
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = '{"is_important": true}'
        mock_init_llm.return_value = mock_llm

        mock_result = MagicMock()
        mock_parser.get_format_instructions.return_value = "format instructions"
        mock_parser.parse.return_value = mock_result

        from app.services.mail.email_importance_service import (
            process_email_comprehensive_analysis,
        )

        result = await process_email_comprehensive_analysis(
            "Subject", "sender@test.com", "2024-01-15", "Email body"
        )
        assert result is mock_result
        mock_init_llm.assert_called_once_with(preferred_provider="gemini")

    @pytest.mark.asyncio
    @patch(f"{MODULE}.email_comprehensive_parser")
    @patch(f"{MODULE}.init_llm")
    async def test_success_with_object_response(
        self, mock_init_llm: MagicMock, mock_parser: MagicMock
    ) -> None:
        response_obj = MagicMock()
        response_obj.text = '{"is_important": false}'
        # Make isinstance(response, str) return False
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = response_obj
        mock_init_llm.return_value = mock_llm

        mock_result = MagicMock()
        mock_parser.get_format_instructions.return_value = "fmt"
        mock_parser.parse.return_value = mock_result

        from app.services.mail.email_importance_service import (
            process_email_comprehensive_analysis,
        )

        result = await process_email_comprehensive_analysis(
            "Subject", "sender@test.com", "2024-01-15", "Body"
        )
        assert result is mock_result

    @pytest.mark.asyncio
    @patch(f"{MODULE}.email_comprehensive_parser")
    @patch(f"{MODULE}.init_llm")
    async def test_parse_error_returns_none(
        self, mock_init_llm: MagicMock, mock_parser: MagicMock
    ) -> None:
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = "bad json"
        mock_init_llm.return_value = mock_llm

        mock_parser.get_format_instructions.return_value = "fmt"
        mock_parser.parse.side_effect = ValueError("parse fail")

        from app.services.mail.email_importance_service import (
            process_email_comprehensive_analysis,
        )

        result = await process_email_comprehensive_analysis(
            "Subject", "sender@test.com", "2024-01-15", "Body"
        )
        # The outer except catches ValueError raised by the inner except
        assert result is None

    @pytest.mark.asyncio
    @patch(f"{MODULE}.init_llm", side_effect=RuntimeError("llm init fail"))
    async def test_outer_exception_returns_none(self, _mock: MagicMock) -> None:
        from app.services.mail.email_importance_service import (
            process_email_comprehensive_analysis,
        )

        result = await process_email_comprehensive_analysis(
            "Subject", "sender@test.com", "2024-01-15", "Body"
        )
        assert result is None


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
