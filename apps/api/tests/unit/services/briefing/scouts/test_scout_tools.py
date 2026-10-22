"""Which integrations a scout watches, where their tools come from, and which of them it may use."""

import hashlib
from types import SimpleNamespace
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

    async def client_for(*, user_id: str) -> MagicMock:
        assert user_id == USER_ID
        return client

    monkeypatch.setattr(scout_tools_module, "get_mcp_client", client_for)
    return client


def _subagent(managed_by: str, *, mcp: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        managed_by=managed_by,
        mcp_config=object() if mcp else None,
        config=SimpleNamespace(tool_space=f"{managed_by}-space"),
    )


class _Registry:
    """A registry whose categories exist only once something registered them."""

    def __init__(self) -> None:
        self.categories: dict[str, list[BaseTool]] = {"native-space": [fetch_digest]}

    def get_category_by_space(self, space: str) -> SimpleNamespace | None:
        tools = self.categories.get(space)
        return None if tools is None else SimpleNamespace(get_tool_objects=lambda: tools)


@pytest.fixture
def native(monkeypatch: pytest.MonkeyPatch) -> _Registry:
    registry = _Registry()
    subagents = {
        "linear": _subagent("composio"),
        "notes": _subagent("native"),
        "todos": _subagent("internal"),
        "empty": _subagent("composio-unregistered"),
    }

    async def register(subagent: SimpleNamespace, into: _Registry) -> str:
        assert (subagent, into) == (subagents["linear"], registry)
        into.categories["composio-space"] = [list_open_tickets, create_ticket]
        return "linear"

    monkeypatch.setattr(scout_tools_module, "get_subagent_by_id", subagents.get)
    monkeypatch.setattr(scout_tools_module, "get_tool_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(scout_tools_module, "register_composio_subagent_tools", register)
    return registry


class TestWhichIntegrations:
    @pytest.mark.usefixtures("native")
    async def test_gaias_own_features_are_not_apps_to_scout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def connected(user_id: str) -> list[dict[str, str]]:
            assert user_id == USER_ID
            return [{"id": "todos", "name": "Todos"}, {"id": "linear", "name": "Linear"}]

        monkeypatch.setattr(scout_tools_module, "get_connected_integrations_named", connected)

        assert await scout_integrations(USER_ID) == [
            ScoutIntegration(integration_id="linear", name="Linear")
        ]

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

        with pytest.raises(AppError) as raised:
            await integration_tools(USER_ID, CUSTOM_MCP)

        error = raised.value
        assert (error.message, error.why, error.fix) == (
            f"no tools reachable for {CUSTOM_MCP}",
            "the integration answered with an empty tool list",
            "reconnect the integration; the scout learns again once its tools are back",
        )

    @pytest.mark.usefixtures("native")
    async def test_a_composio_integration_registers_its_tools_then_reads_its_category(
        self,
    ) -> None:
        tools = await integration_tools(USER_ID, "linear")

        assert tools == [list_open_tickets, create_ticket]

    @pytest.mark.usefixtures("native")
    async def test_a_built_in_integration_reads_its_category_without_registering(self) -> None:
        assert await integration_tools(USER_ID, "notes") == [fetch_digest]

    @pytest.mark.usefixtures("native")
    async def test_an_integration_with_no_category_has_no_tools(self) -> None:
        with pytest.raises(AppError):
            await integration_tools(USER_ID, "empty")


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
        destructive = AsyncMock(
            side_effect=lambda name, description: description == purge_queue.description
        )
        monkeypatch.setattr(scout_tools_module, "is_tool_destructive", destructive)

        result = await scout_tools(USER_ID, CUSTOM_MCP)

        assert list(result.read_only) == ["list_open_tickets"]
        assert result.fingerprint == tool_fingerprint(
            [list_open_tickets, create_ticket, purge_queue, fetch_digest]
        )

    def test_the_fingerprint_is_the_hash_of_the_sorted_names(self) -> None:
        names = b"create_ticket\nlist_open_tickets"

        assert tool_fingerprint([list_open_tickets, create_ticket]) == (
            hashlib.sha256(names).hexdigest()
        )

    async def test_the_fingerprint_covers_every_tool_and_ignores_order(self) -> None:
        assert tool_fingerprint([list_open_tickets, create_ticket]) == tool_fingerprint(
            [create_ticket, list_open_tickets]
        )
        assert tool_fingerprint([list_open_tickets]) != tool_fingerprint(
            [list_open_tickets, create_ticket]
        )
