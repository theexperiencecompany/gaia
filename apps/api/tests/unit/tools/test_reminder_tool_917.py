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

import pytest

from app.models.reminder_models import AgentType, ReminderDocument

# ---------------------------------------------------------------------------
# Module-level patch for rate limiting
# ---------------------------------------------------------------------------
_rl_patch = patch(
    "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
    new_callable=AsyncMock,
    return_value={},
)
_rl_patch.start()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"
MODULE = "app.agents.tools.reminder_tool"


def _cfg() -> dict[str, Any]:
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

        from app.agents.tools.reminder_tool import search_reminders_tool

        result = await search_reminders_tool.coroutine(config=_cfg(), query="dentist")  # type: ignore[attr-defined]

        assert isinstance(result, list), f"search failed: {result}"
        assert len(result) == 1
        assert result[0]["id"] == "rem-917"

    @patch(f"{MODULE}.reminder_scheduler")
    async def test_search_payload_is_json_safe(self, mock_scheduler: MagicMock) -> None:
        doc = _reminder_document()
        mock_scheduler.list_user_reminders = AsyncMock(return_value=[doc])

        from app.agents.tools.reminder_tool import search_reminders_tool

        result = await search_reminders_tool.coroutine(config=_cfg(), query="dentist")  # type: ignore[attr-defined]

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

        from app.agents.tools.reminder_tool import list_user_reminders_tool

        result = await list_user_reminders_tool.coroutine(config=_cfg())  # type: ignore[attr-defined]

        assert isinstance(result, list)
        assert isinstance(result[0]["scheduled_at"], str)
        _assert_json_safe(result)

    @patch(f"{MODULE}.reminder_scheduler")
    async def test_get_payload_is_json_safe(self, mock_scheduler: MagicMock) -> None:
        mock_scheduler.get_reminder = AsyncMock(return_value=_reminder_document())

        from app.agents.tools.reminder_tool import get_reminder_tool

        result = await get_reminder_tool.coroutine(config=_cfg(), reminder_id="rem-917")  # type: ignore[attr-defined]

        assert result["id"] == "rem-917"
        assert isinstance(result["scheduled_at"], str)
        _assert_json_safe(result)
