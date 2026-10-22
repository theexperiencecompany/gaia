"""Which integrations a scout watches, where their tools come from, and which of them it may use."""

from typing import Annotated
from unittest.mock import AsyncMock, MagicMock

from langchain_core.tools import BaseTool, tool
import pytest

from app.services.briefing.scouts import tools as scout_tools_module
from app.services.briefing.scouts.tools import (
    ScoutIntegration,
    integration_tools,
    scout_integrations,
    scout_tools,
    tool_fingerprint,
)
from app.services.mcp.langchain_adapter import MCP_ANNOTATIONS_METADATA_KEY
from app.utils.errors import AppError

USER_ID = "64f1c0ffee0000000000abcd"
CUSTOM_MCP = "3f2c9a1e-custom-mcp"


@tool
async def list_open_tickets(queue: Annotated[str, "Queue"]) -> str:
    """List open tickets."""
    return "[]"


@tool
async def create_ticket(title: Annotated[str, "Title"]) -> str:
    """Create a ticket."""
    return "{}"


@tool
async def purge_queue(queue: Annotated[str, "Queue"]) -> str:
    """Remove everything in a queue."""
    return "{}"


@tool
async def fetch_digest(queue: Annotated[str, "Queue"]) -> str:
    """Fetch a digest."""
    return "{}"


def _flagged_destructive(base: BaseTool) -> BaseTool:
    flagged = base.model_copy()
    flagged.metadata = {MCP_ANNOTATIONS_METADATA_KEY: {"destructiveHint": True}}
    return flagged


@pytest.fixture
def mcp_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    client = MagicMock()
    client.ensure_connected = AsyncMock(return_value=[list_open_tickets, create_ticket])
    monkeypatch.setattr(scout_tools_module, "get_mcp_client", AsyncMock(return_value=client))
    return client


class TestWhichIntegrations:
    async def test_mail_and_calendar_are_left_to_their_own_sections(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connected = [
            {"id": "gmail", "name": "Gmail"},
            {"id": "googlecalendar", "name": "Google Calendar"},
            {"id": "linear", "name": "Linear"},
            {"id": CUSTOM_MCP, "name": "Helpdesk"},
        ]
        monkeypatch.setattr(
            scout_tools_module,
            "get_connected_integrations_named",
            AsyncMock(return_value=connected),
        )

        assert await scout_integrations(USER_ID) == [
            ScoutIntegration(integration_id="linear", name="Linear"),
            ScoutIntegration(integration_id=CUSTOM_MCP, name="Helpdesk"),
        ]


class TestWhereToolsComeFrom:
    async def test_a_custom_mcp_is_read_from_the_users_own_mcp_client(
        self, mcp_client: MagicMock
    ) -> None:
        tools = await integration_tools(USER_ID, CUSTOM_MCP)

        mcp_client.ensure_connected.assert_awaited_once_with(CUSTOM_MCP)
        assert [t.name for t in tools] == ["list_open_tickets", "create_ticket"]

    async def test_an_integration_with_no_reachable_tools_fails_loud(
        self, mcp_client: MagicMock
    ) -> None:
        mcp_client.ensure_connected.return_value = []

        with pytest.raises(AppError, match="no tools reachable"):
            await integration_tools(USER_ID, CUSTOM_MCP)


class TestReadOnly:
    async def test_only_tools_nothing_marks_as_writing_are_kept(
        self, monkeypatch: pytest.MonkeyPatch, mcp_client: MagicMock
    ) -> None:
        mcp_client.ensure_connected.return_value = [
            list_open_tickets,
            create_ticket,
            purge_queue,
            _flagged_destructive(fetch_digest),
        ]
        destructive = AsyncMock(side_effect=lambda name, description: name == "purge_queue")
        monkeypatch.setattr(scout_tools_module, "is_tool_destructive", destructive)

        result = await scout_tools(USER_ID, CUSTOM_MCP)

        assert list(result.read_only) == ["list_open_tickets"]

    async def test_the_fingerprint_covers_every_tool_and_ignores_order(self) -> None:
        assert tool_fingerprint([list_open_tickets, create_ticket]) == tool_fingerprint(
            [create_ticket, list_open_tickets]
        )
        assert tool_fingerprint([list_open_tickets]) != tool_fingerprint(
            [list_open_tickets, create_ticket]
        )
