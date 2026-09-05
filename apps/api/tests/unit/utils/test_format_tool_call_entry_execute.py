"""format_tool_call_entry must render an execute-proxied call as its REAL tool.

Without the unwrap every proxied card in the "Used N tools" thread collapses to
a generic "Execute" row: wrong name, wrong category/icon, envelope as inputs.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.agent_utils import format_tool_call_entry

REGISTRY_PATCH = "app.utils.agent_utils.get_tool_registry"


def _registry(category: str = "GMAIL") -> MagicMock:
    registry = MagicMock()
    registry.get_category_of_tool.return_value = category
    registry.get_all_tools_for_search.return_value = []
    return registry


def _execute_call(**overrides: Any) -> dict[str, Any]:
    call: dict[str, Any] = {
        "name": "execute",
        "id": "tc-exec-1",
        "args": {
            "task_description": "Sending the reply to Bob",
            "tool_name": "GMAIL_SEND_EMAIL",
            "data": {"recipient_email": "bob@example.com", "subject": "Re: deck"},
        },
    }
    call.update(overrides)
    return call


@pytest.mark.unit
class TestExecuteProxyRendering:
    async def test_card_carries_the_real_tool_identity(self) -> None:
        with patch(REGISTRY_PATCH, new_callable=AsyncMock, return_value=_registry()):
            entry = await format_tool_call_entry(_execute_call())  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall
        assert entry is not None
        data = entry["data"]
        assert data["tool_name"] == "GMAIL_SEND_EMAIL"
        assert data["tool_category"] == "GMAIL"
        assert data["inputs"] == {"recipient_email": "bob@example.com", "subject": "Re: deck"}

    async def test_task_description_is_the_display_label(self) -> None:
        with patch(REGISTRY_PATCH, new_callable=AsyncMock, return_value=_registry()):
            entry = await format_tool_call_entry(_execute_call())  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall
        assert entry is not None
        assert entry["data"]["message"] == "Sending the reply to Bob"
        assert entry["data"]["show_category"] is False

    async def test_missing_task_description_falls_back_to_humanized_name(self) -> None:
        call = _execute_call()
        del call["args"]["task_description"]
        with patch(REGISTRY_PATCH, new_callable=AsyncMock, return_value=_registry()):
            entry = await format_tool_call_entry(call)  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall
        assert entry is not None
        assert "Execute" not in entry["data"]["message"]
        assert entry["data"]["tool_name"] == "GMAIL_SEND_EMAIL"

    async def test_malformed_execute_renders_as_itself(self) -> None:
        call = _execute_call(args={"task_description": "d", "data": {}})
        with patch(REGISTRY_PATCH, new_callable=AsyncMock, return_value=_registry("execute")):
            entry = await format_tool_call_entry(call)  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall
        assert entry is not None
        assert entry["data"]["tool_name"] == "execute"

    async def test_direct_call_rendering_is_unchanged(self) -> None:
        call = {"name": "get_weather", "args": {"city": "Berlin"}, "id": "tc5"}
        with patch(REGISTRY_PATCH, new_callable=AsyncMock, return_value=_registry("weather")):
            entry = await format_tool_call_entry(call)  # type: ignore[arg-type]  # hand-built dict stands in for a ToolCall
        assert entry is not None
        assert entry["data"]["tool_name"] == "get_weather"
        assert entry["data"]["inputs"] == {"city": "Berlin"}
