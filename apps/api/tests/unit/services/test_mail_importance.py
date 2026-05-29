"""Unit tests for app/services/mail/email_importance_service.py.

Behavior spec
=============

UNIT: get_email_importance_summaries(user_id, limit=50, important_only=False)
EXPECTED: Query mail_collection for the user's analyzed emails, newest first,
          capped at `limit`; serialise each doc (_id -> str, analyzed_at -> ISO);
          return {"status","emails","count","filtered_by_importance"}.
MECHANISM: find({"user_id": user_id[, "is_important": True]}).sort("analyzed_at", -1)
           .limit(limit); to_list(length=limit); mutate docs in place; return dict.
MUST-CATCH:
  - query filter key is exactly "user_id" with the given id              [L33]
  - sort is exactly ("analyzed_at", -1) — newest first                   [L38]
  - default limit is 50 (passed to .limit and to_list)                   [L17]
  - important_only adds {"is_important": True} and sets the flag         [L34/L52]
  - _id is stringified and analyzed_at becomes an ISO string             [L43/L46]
  - a doc without analyzed_at is passed through untouched (branch)       [L45]
  - DB failure propagates (no swallow)                                   [L54-56]

UNIT: get_single_email_importance_summary(user_id, message_id)
EXPECTED: find_one by user+message; None if absent; else serialise and wrap.
MECHANISM: find_one({"user_id","message_id"}); if None -> None; _id/analyzed_at;
           return {"status":"success","email":email}.
MUST-CATCH:
  - find_one filter is exactly {"user_id","message_id"} with given ids   [L75]
  - missing email returns None (early return)                            [L77-78]
  - _id stringified and analyzed_at converted to its ISO value           [L81/L83-84]
  - doc without analyzed_at left untouched (branch)                      [L83]
  - DB failure propagates                                                [L87-89]

UNIT: process_email_comprehensive_analysis(subject, sender, date, content)
EXPECTED: init gemini LLM, format prompt, invoke; parse str-or-obj response with
          the pydantic parser; return parsed model; None on any failure.
MECHANISM: init_llm("gemini"); prompt.format(...); ainvoke; str.strip() else
           response.text; parser.parse(text); inner parse failure -> ValueError
           -> outer except -> None; any outer failure -> None.
MUST-CATCH:
  - init_llm called with preferred_provider="gemini"                     [L111]
  - string response is parsed and the parsed model returned              [L125-126/133]
  - non-string response uses response.text                               [L128]
  - parse failure yields None (inner raise -> outer swallow)             [L137-140/142-144]
  - failure before/at invoke yields None                                 [L142-144]

UNIT: get_bulk_email_importance_summaries(user_id, message_ids)
EXPECTED: find all matching docs, serialise, index by message_id, report
          found/missing message ids and counts.
MECHANISM: find({"user_id","message_id":{"$in":ids}}); to_list(len(ids));
           _id/analyzed_at per doc; map by message_id; set diff for missing.
MUST-CATCH:
  - filter is exactly {"user_id","message_id":{"$in": ids}}              [L166]
  - _id stringified and analyzed_at converted to ISO                     [L174/L175-176]
  - found/missing counts + id lists are correct on partial match         [L183-192]
  - returned dict carries the exact "emails"/"found_message_ids" keys    [L188/L191]
  - DB failure propagates                                                [L194-196]

EQUIVALENT MUTANTS (justified survivors):
  - L140 const_str "Failed to parse AI response..." -> "": the ValueError is
    raised inside the inner except and immediately caught by the outer
    `except Exception` (L142), which logs and returns None. The message string
    is never observable by the caller — return value is None either way and
    only the log text differs. Behaviour-preserving, so unkillable by design.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.mail_models import (
    EmailComprehensiveAnalysis,
    EmailImportanceLevelEnum,
)
from app.services.mail.email_importance_service import (
    get_bulk_email_importance_summaries,
    get_email_importance_summaries,
    get_single_email_importance_summary,
    process_email_comprehensive_analysis,
)

MODULE = "app.services.mail.email_importance_service"

_ANALYZED_AT = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
_ANALYZED_AT_ISO = _ANALYZED_AT.isoformat()


def _make_email_doc(
    message_id: str = "msg-1",
    user_id: str = "user-1",
    is_important: bool = True,
) -> dict[str, Any]:
    return {
        "_id": MagicMock(),  # ObjectId-like; stringified by the service
        "user_id": user_id,
        "message_id": message_id,
        "is_important": is_important,
        "analyzed_at": _ANALYZED_AT,
        "subject": "Test email",
    }


def _mock_find_cursor(docs: list[dict[str, Any]]) -> MagicMock:
    """Cursor supporting .sort().limit().to_list() (the list-query shape)."""
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=docs)
    return cursor


def _mock_bulk_cursor(docs: list[dict[str, Any]]) -> MagicMock:
    """Cursor supporting .to_list() directly (the bulk-query shape)."""
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=docs)
    return cursor


@pytest.fixture(autouse=True)
def _patch_log():
    with patch(f"{MODULE}.log"):
        yield


class TestGetEmailImportanceSummaries:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_returns_serialised_emails_newest_first(self, mock_coll: MagicMock) -> None:
        docs = [_make_email_doc("msg-1"), _make_email_doc("msg-2")]
        cursor = _mock_find_cursor(docs)
        mock_coll.find.return_value = cursor

        result = await get_email_importance_summaries("user-1", limit=50)

        assert result["status"] == "success"
        assert result["count"] == 2
        assert result["filtered_by_importance"] is False
        # Filter key + value are exact (kills "user_id" -> "").
        assert mock_coll.find.call_args[0][0] == {"user_id": "user-1"}
        # Newest-first sort is exact (kills "analyzed_at" -> "" and -1 -> -2).
        cursor.sort.assert_called_once_with("analyzed_at", -1)
        # _id stringified, analyzed_at carries the real ISO value.
        assert result["emails"][0]["_id"] == str(docs[0]["_id"])
        assert result["emails"][0]["analyzed_at"] == _ANALYZED_AT_ISO

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_default_limit_is_fifty(self, mock_coll: MagicMock) -> None:
        cursor = _mock_find_cursor([])
        mock_coll.find.return_value = cursor

        await get_email_importance_summaries("user-1")

        # Default limit threads through both .limit() and to_list(length=...).
        cursor.limit.assert_called_once_with(50)
        cursor.to_list.assert_awaited_once_with(length=50)

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_explicit_limit_overrides_default(self, mock_coll: MagicMock) -> None:
        cursor = _mock_find_cursor([])
        mock_coll.find.return_value = cursor

        await get_email_importance_summaries("user-1", limit=7)

        cursor.limit.assert_called_once_with(7)
        cursor.to_list.assert_awaited_once_with(length=7)

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_important_only_filter(self, mock_coll: MagicMock) -> None:
        docs = [_make_email_doc("msg-1", is_important=True)]
        mock_coll.find.return_value = _mock_find_cursor(docs)

        result = await get_email_importance_summaries("user-1", important_only=True)

        assert result["filtered_by_importance"] is True
        assert mock_coll.find.call_args[0][0] == {"user_id": "user-1", "is_important": True}

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_not_important_only_omits_flag(self, mock_coll: MagicMock) -> None:
        mock_coll.find.return_value = _mock_find_cursor([])

        await get_email_importance_summaries("user-1", important_only=False)

        # is_important must NOT be added when important_only is False.
        assert "is_important" not in mock_coll.find.call_args[0][0]

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_doc_without_analyzed_at_passed_through(self, mock_coll: MagicMock) -> None:
        doc = {"_id": MagicMock(), "user_id": "user-1", "message_id": "msg-1"}
        mock_coll.find.return_value = _mock_find_cursor([doc])

        result = await get_email_importance_summaries("user-1")

        assert result["count"] == 1
        assert "analyzed_at" not in result["emails"][0]

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_db_error_propagates(self, mock_coll: MagicMock) -> None:
        mock_coll.find.side_effect = RuntimeError("db error")

        with pytest.raises(RuntimeError, match="db error"):
            await get_email_importance_summaries("user-1")


class TestGetSingleEmailImportanceSummary:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_email_found_is_serialised(self, mock_coll: MagicMock) -> None:
        doc = _make_email_doc("msg-1")
        mock_coll.find_one = AsyncMock(return_value=doc)

        result = await get_single_email_importance_summary("user-1", "msg-1")

        assert result is not None
        assert result["status"] == "success"
        # Lookup filter is exact (kills both "user_id"/"message_id" -> "").
        mock_coll.find_one.assert_awaited_once_with({"user_id": "user-1", "message_id": "msg-1"})
        assert result["email"]["_id"] == str(doc["_id"])
        # analyzed_at converted to its real ISO value (kills L83/L84 str mutants).
        assert result["email"]["analyzed_at"] == _ANALYZED_AT_ISO

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_email_not_found_returns_none(self, mock_coll: MagicMock) -> None:
        mock_coll.find_one = AsyncMock(return_value=None)

        result = await get_single_email_importance_summary("user-1", "msg-999")

        assert result is None

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_doc_without_analyzed_at_passed_through(self, mock_coll: MagicMock) -> None:
        doc = {"_id": MagicMock(), "user_id": "user-1", "message_id": "msg-1"}
        mock_coll.find_one = AsyncMock(return_value=doc)

        result = await get_single_email_importance_summary("user-1", "msg-1")

        assert result is not None
        assert "analyzed_at" not in result["email"]

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_db_error_propagates(self, mock_coll: MagicMock) -> None:
        mock_coll.find_one = AsyncMock(side_effect=RuntimeError("db error"))

        with pytest.raises(RuntimeError, match="db error"):
            await get_single_email_importance_summary("user-1", "msg-1")


def _analysis() -> EmailComprehensiveAnalysis:
    return EmailComprehensiveAnalysis(
        is_important=True,
        importance_level=EmailImportanceLevelEnum.HIGH,
        summary="A real summary",
        semantic_labels=["work", "urgent"],
    )


class TestProcessEmailComprehensiveAnalysis:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.email_comprehensive_parser")
    @patch(f"{MODULE}.init_llm")
    async def test_string_response_is_parsed(
        self, mock_init_llm: MagicMock, mock_parser: MagicMock
    ) -> None:
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = '  {"is_important": true}  '
        mock_init_llm.return_value = mock_llm

        parsed = _analysis()
        mock_parser.get_format_instructions.return_value = "format instructions"
        mock_parser.parse.return_value = parsed

        result = await process_email_comprehensive_analysis(
            "Subject", "sender@test.com", "2024-01-15", "Email body"
        )

        assert result is parsed
        mock_init_llm.assert_called_once_with(preferred_provider="gemini")
        # str branch strips whitespace before parsing.
        mock_parser.parse.assert_called_once_with('{"is_important": true}')

    @pytest.mark.asyncio
    @patch(f"{MODULE}.email_comprehensive_parser")
    @patch(f"{MODULE}.init_llm")
    async def test_object_response_uses_text_attr(
        self, mock_init_llm: MagicMock, mock_parser: MagicMock
    ) -> None:
        response_obj = MagicMock()
        response_obj.text = '{"is_important": false}'
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = response_obj
        mock_init_llm.return_value = mock_llm

        parsed = _analysis()
        mock_parser.get_format_instructions.return_value = "fmt"
        mock_parser.parse.return_value = parsed

        result = await process_email_comprehensive_analysis(
            "Subject", "sender@test.com", "2024-01-15", "Body"
        )

        assert result is parsed
        # Non-string response is parsed from .text (kills the str/else branch swap).
        mock_parser.parse.assert_called_once_with('{"is_important": false}')

    @pytest.mark.asyncio
    @patch(f"{MODULE}.email_comprehensive_parser")
    @patch(f"{MODULE}.init_llm")
    async def test_parse_failure_returns_none(
        self, mock_init_llm: MagicMock, mock_parser: MagicMock
    ) -> None:
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = "bad json"
        mock_init_llm.return_value = mock_llm

        mock_parser.get_format_instructions.return_value = "fmt"
        mock_parser.parse.side_effect = ValueError("parse fail")

        result = await process_email_comprehensive_analysis(
            "Subject", "sender@test.com", "2024-01-15", "Body"
        )

        # Inner except re-raises ValueError; outer except swallows -> None.
        assert result is None

    @pytest.mark.asyncio
    @patch(f"{MODULE}.init_llm", side_effect=RuntimeError("llm init fail"))
    async def test_failure_before_invoke_returns_none(self, _mock: MagicMock) -> None:
        result = await process_email_comprehensive_analysis(
            "Subject", "sender@test.com", "2024-01-15", "Body"
        )

        assert result is None


class TestGetBulkEmailImportanceSummaries:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_all_found_serialised_and_indexed(self, mock_coll: MagicMock) -> None:
        docs = [_make_email_doc("msg-1"), _make_email_doc("msg-2")]
        mock_coll.find.return_value = _mock_bulk_cursor(docs)

        result = await get_bulk_email_importance_summaries("user-1", ["msg-1", "msg-2"])

        assert result["status"] == "success"
        assert result["found_count"] == 2
        assert result["missing_count"] == 0
        # Filter shape is exact (kills "user_id"/"message_id"/"$in" -> "").
        assert mock_coll.find.call_args[0][0] == {
            "user_id": "user-1",
            "message_id": {"$in": ["msg-1", "msg-2"]},
        }
        # Returned mapping keyed by message_id; _id + analyzed_at serialised.
        assert set(result["emails"].keys()) == {"msg-1", "msg-2"}
        assert result["emails"]["msg-1"]["_id"] == str(docs[0]["_id"])
        assert result["emails"]["msg-1"]["analyzed_at"] == _ANALYZED_AT_ISO
        assert sorted(result["found_message_ids"]) == ["msg-1", "msg-2"]

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_partial_match_reports_missing(self, mock_coll: MagicMock) -> None:
        docs = [_make_email_doc("msg-1")]
        mock_coll.find.return_value = _mock_bulk_cursor(docs)

        result = await get_bulk_email_importance_summaries("user-1", ["msg-1", "msg-2"])

        assert result["found_count"] == 1
        assert result["missing_count"] == 1
        assert result["found_message_ids"] == ["msg-1"]
        assert result["missing_message_ids"] == ["msg-2"]

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_doc_without_analyzed_at_passed_through(self, mock_coll: MagicMock) -> None:
        doc = {"_id": MagicMock(), "user_id": "user-1", "message_id": "msg-1"}
        mock_coll.find.return_value = _mock_bulk_cursor([doc])

        result = await get_bulk_email_importance_summaries("user-1", ["msg-1"])

        assert result["found_count"] == 1
        assert "analyzed_at" not in result["emails"]["msg-1"]

    @pytest.mark.asyncio
    @patch(f"{MODULE}.mail_collection")
    async def test_db_error_propagates(self, mock_coll: MagicMock) -> None:
        mock_coll.find.side_effect = RuntimeError("db error")

        with pytest.raises(RuntimeError, match="db error"):
            await get_bulk_email_importance_summaries("user-1", ["msg-1"])
