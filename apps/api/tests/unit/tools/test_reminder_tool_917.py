"""Regression tests for issue #917 — search_reminders_tool failed every call.

The reminder read tools serialized real ``ReminderDocument``s in python mode,
which keeps native ``datetime`` objects (the Mongo write path needs them).
Feeding that dump to stdlib ``json.dumps`` raised "Object of type datetime is
not JSON serializable" on every search call, while list/get silently degraded
their datetime fields to Python reprs inside the ToolMessage. These tests pin
the boundary contract: reminder tool payloads are JSON-safe with ISO datetime
strings — the same ``model_dump(mode="json")`` convention every other tool
family follows.
"""

from datetime import UTC, datetime, timedelta
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables.config import RunnableConfig
import pytest

from app.agents.tools.reminder_tool import (
    get_reminder_tool,
    list_user_reminders_tool,
    search_reminders_tool,
)
from app.models.reminder_models import AgentType, ReminderDocument

FAKE_USER_ID = "507f1f77bcf86cd799439011"
MODULE = "app.agents.tools.reminder_tool"


def _cfg() -> RunnableConfig:
    return {"configurable": {"user_id": FAKE_USER_ID, "user_timezone": "Asia/Kolkata"}}


def _reminder_document(
    reminder_id: str = "rem-917", title: str = "Dentist check-up"
) -> ReminderDocument:
    """A real document, not a mock — its ``model_dump()`` carries datetimes."""
    return ReminderDocument(
        id=reminder_id,
        user_id=FAKE_USER_ID,
        agent=AgentType.STATIC,
        payload={"title": title, "body": "Six-month cleaning appointment"},
        scheduled_at=datetime.now(UTC) + timedelta(days=2),
    )


@pytest.fixture(autouse=True)
def _no_rate_limiting():
    """Keep the rate-limit mock scoped to this module's tests."""
    with patch(
        "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
        new_callable=AsyncMock,
        return_value={},
    ):
        yield


def _assert_json_safe(payload: Any) -> None:
    """A tool result crosses into a ToolMessage as text — it must survive
    strict JSON encoding with no datetime objects and no Python reprs."""
    json.dumps(payload)
    if isinstance(payload, dict):
        for value in payload.values():
            assert not isinstance(value, datetime), (
                f"raw datetime leaked into tool payload: {value!r}"
            )
    elif isinstance(payload, list):
        for item in payload:
            _assert_json_safe(item)


# ---------------------------------------------------------------------------
# Tests: search_reminders_tool (#917)
# ---------------------------------------------------------------------------


@pytest.mark.regression
class TestSearchRemindersTool917:
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_search_matches_real_documents(self, mock_scheduler: MagicMock) -> None:
        doc = _reminder_document()
        other = _reminder_document(reminder_id="rem-other", title="Car service")
        mock_scheduler.list_user_reminders = AsyncMock(return_value=[doc, other])

        result = await search_reminders_tool.ainvoke({"query": "dentist"}, config=_cfg())

        assert isinstance(result, list), f"search failed: {result}"
        assert len(result) == 1
        assert result[0]["id"] == "rem-917"

    @patch(f"{MODULE}.reminder_scheduler")
    async def test_search_payload_is_json_safe(self, mock_scheduler: MagicMock) -> None:
        doc = _reminder_document()
        mock_scheduler.list_user_reminders = AsyncMock(return_value=[doc])

        result = await search_reminders_tool.ainvoke({"query": "dentist"}, config=_cfg())

        assert isinstance(result, list), f"search failed: {result}"
        assert isinstance(result[0]["scheduled_at"], str)
        _assert_json_safe(result)


# ---------------------------------------------------------------------------
# Tests: list/get payloads cross the same boundary
# ---------------------------------------------------------------------------


@pytest.mark.regression
class TestReminderReadToolsJsonSafePayloads917:
    @patch(f"{MODULE}.reminder_scheduler")
    async def test_list_payload_is_json_safe(self, mock_scheduler: MagicMock) -> None:
        mock_scheduler.list_user_reminders = AsyncMock(return_value=[_reminder_document()])

        result = await list_user_reminders_tool.ainvoke({}, config=_cfg())

        assert isinstance(result, list)
        assert isinstance(result[0]["scheduled_at"], str)
        _assert_json_safe(result)

    @patch(f"{MODULE}.reminder_scheduler")
    async def test_get_payload_is_json_safe(self, mock_scheduler: MagicMock) -> None:
        doc = _reminder_document()
        mock_scheduler.get_reminder = AsyncMock(return_value=doc)

        result = await get_reminder_tool.ainvoke({"reminder_id": "rem-917"}, config=_cfg())

        assert result["id"] == "rem-917"
        assert isinstance(result["scheduled_at"], str)
        _assert_json_safe(result)
