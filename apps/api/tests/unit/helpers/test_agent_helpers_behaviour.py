"""What the silent run hands the tool-card formatter for each tool call."""

from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage
from langchain_core.messages.tool import ToolCall
import pytest

from app.helpers.agent_helpers import _collect_silent_tool_entries
from app.models.chat_models import ToolDataEntry

USER_ID = "507f1f77bcf86cd799439011"


@pytest.mark.unit
class TestCollectSilentToolEntriesFormatsTheCallItSaw:
    async def test_the_formatter_receives_the_tool_call_and_the_runs_user(self) -> None:
        call = ToolCall(id="tc1", name="custom_tool", args={"q": "x"}, type="tool_call")
        entry = ToolDataEntry(tool_name="custom_tool", data={"q": "x"}, timestamp="t")
        entries: list[ToolDataEntry] = []
        emitted: set[str] = set()

        with patch(
            "app.helpers.agent_helpers.format_tool_call_entry",
            new=AsyncMock(return_value=entry),
        ) as format_entry:
            await _collect_silent_tool_entries(
                [AIMessage(content="", tool_calls=[call])], emitted, entries, USER_ID
            )

        format_entry.assert_awaited_once_with(call, user_id=USER_ID)
        assert entries == [entry]
        assert emitted == {"tc1"}
