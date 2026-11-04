"""Which integration an activate_integration card names."""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages.tool import ToolCall
import pytest

from app.utils.agent_utils import format_tool_call_entry

MODULE = "app.utils.agent_utils"
DISPLAY = {
    "custom_srv": ("https://icons.test/custom.png", "Custom Server"),
    "explicit": ("https://icons.test/explicit.png", "Explicit"),
}


async def _display(integration_id: str) -> tuple[str | None, str | None]:
    return DISPLAY[integration_id]


def _call(name: str, args: dict[str, object]) -> ToolCall:
    return ToolCall(id="tc1", name=name, args=args, type="tool_call")


async def _format(
    call: ToolCall, integration_id: str | None = None
) -> tuple[dict[str, object], AsyncMock]:
    registry = MagicMock()
    registry.get_category_of_tool.return_value = "unknown"
    registry.get_all_tools_for_search.return_value = []
    display = AsyncMock(side_effect=_display)
    with (
        patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)),
        patch(f"{MODULE}._integration_display", new=display),
    ):
        entry = await format_tool_call_entry(call, integration_id=integration_id)
    assert entry is not None
    data: dict[str, object] = entry["data"]
    return data, display


@pytest.mark.unit
class TestActivateIntegrationCardNamesItsIntegration:
    async def test_the_card_names_the_integration_the_call_activates(self) -> None:
        data, display = await _format(
            _call("activate_integration", {"integration_id": "custom_srv"})
        )

        display.assert_awaited_once_with("custom_srv")
        assert data["icon_url"] == "https://icons.test/custom.png"
        assert data["integration_name"] == "Custom Server"

    async def test_an_integration_the_caller_already_knows_is_not_overwritten_by_the_args(
        self,
    ) -> None:
        data, display = await _format(
            _call("activate_integration", {"integration_id": "custom_srv"}),
            integration_id="explicit",
        )

        display.assert_awaited_once_with("explicit")
        assert data["integration_name"] == "Explicit"

    async def test_another_special_tool_never_reads_an_integration_from_its_args(self) -> None:
        data, display = await _format(_call("call_executor", {"integration_id": "custom_srv"}))

        display.assert_not_awaited()
        assert data["icon_url"] is None
        assert data["integration_name"] is None

    async def test_an_activation_without_an_integration_id_names_none(self) -> None:
        data, display = await _format(_call("activate_integration", {}))

        display.assert_not_awaited()
        assert data["integration_name"] is None
