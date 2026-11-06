"""What the user-facing warning about renamed stored MCP tools says."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.constants.mcp import MCP_RENAMED_TOOL_NOTE
from app.models.integration_models import StoredIntegrationTool
from app.services.tools.tools_service import get_integration_tool_list
from tests.helpers import captured_wide_event

MODULE = "app.services.tools.tools_service"


@pytest.mark.unit
class TestRenamedStoredToolsWarning:
    async def test_the_warning_says_renamed_tools_are_not_listed(self) -> None:
        registry = MagicMock()
        registry.get_all_category_objects.return_value = {}
        stored = [
            StoredIntegrationTool(
                name="posthog_execute",
                description=MCP_RENAMED_TOOL_NOTE.format(
                    original="execute", renamed="posthog_execute"
                ),
            ),
        ]
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(f"{MODULE}.get_integration_tools", new=AsyncMock(return_value=stored)),
        ):
            async with captured_wide_event() as event:
                listed = await get_integration_tool_list("posthog")

        assert listed == []
        (warning,) = event["warnings"]
        assert warning["msg"] == (
            f"{LogTag.TOOL} Stored MCP tool list holds renames; those tools are not listed"
        )
