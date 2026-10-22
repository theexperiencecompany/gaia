"""Which integrations a scout watches, where their tools come from, and which of them it may use."""

import hashlib
from types import SimpleNamespace
from typing import Annotated
from unittest.mock import AsyncMock, MagicMock

from langchain_core.tools import BaseTool, tool
import pytest

from app.constants.hil import COMPOSIO_TAGS_METADATA_KEY
from app.constants.scouts import SCOUT_MAX_BOUND_TOOLS, SCOUT_TOOL_QUERY
from app.services.briefing.scouts import tools as scout_tools_module
from app.services.briefing.scouts.tools import (
    ScoutIntegration,
    ScoutTools,
    bound_tools,
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


def _annotated(base: BaseTool, **annotations: bool) -> BaseTool:
    return base.model_copy(update={"metadata": {MCP_ANNOTATIONS_METADATA_KEY: annotations}})


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
        config=SimpleNamespace(tool_space=f"{managed_by}-space", specific_tools=None),
    )


class _Registry:
    """A registry whose categories exist only once something registered them."""

    def __init__(self) -> None:
        self.categories: dict[str, list[BaseTool]] = {"native-space": [fetch_digest]}

    def get_category_by_space(self, space: str) -> SimpleNamespace | None:
        tools = self.categories.get(space)
        return None if tools is None else SimpleNamespace(get_tool_objects=lambda: tools)


#: Composio's own tags for the toolkit, as its raw tool list carries them.
_COMPOSIO_TAGS = {
    "list_open_tickets": ["openWorldHint", "readOnlyHint"],
    "create_ticket": ["createHint", "openWorldHint"],
}


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
        return "LINEAR"

    async def raw_tools(tool_kit: str, specific_tools: list[str] | None) -> list[SimpleNamespace]:
        assert (tool_kit, specific_tools) == ("LINEAR", None)
        return [SimpleNamespace(slug=slug, tags=tags) for slug, tags in _COMPOSIO_TAGS.items()]

    monkeypatch.setattr(scout_tools_module, "get_subagent_by_id", subagents.get)
    monkeypatch.setattr(scout_tools_module, "get_tool_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(scout_tools_module, "register_composio_subagent_tools", register)
    monkeypatch.setattr(
        scout_tools_module,
        "get_composio_service",
        lambda: SimpleNamespace(get_raw_tools_metadata=raw_tools),
    )
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
    async def test_a_composio_tool_carries_its_composio_tags_on_a_scout_copy(self) -> None:
        tools = await integration_tools(USER_ID, "linear")

        assert [(t.name, (t.metadata or {}).get(COMPOSIO_TAGS_METADATA_KEY)) for t in tools] == [
            ("list_open_tickets", ["openWorldHint", "readOnlyHint"]),
            ("create_ticket", ["createHint", "openWorldHint"]),
        ]
        # The registry's shared tool objects are never written to.
        assert list_open_tickets.metadata is None

    @pytest.mark.usefixtures("native")
    async def test_a_built_in_integration_reads_its_category_without_registering(self) -> None:
        assert await integration_tools(USER_ID, "notes") == [fetch_digest]

    @pytest.mark.usefixtures("native")
    async def test_an_integration_with_no_category_has_no_tools(self) -> None:
        with pytest.raises(AppError):
            await integration_tools(USER_ID, "empty")


class TestReadOnly:
    @pytest.mark.regression
    async def test_an_mcp_tool_is_a_scouts_only_when_it_declares_itself_read_only(
        self, mcp_client: MagicMock
    ) -> None:
        """The name-and-HIL check passed verify-domain and manage_x_play as read-only."""
        mcp_client.ensure_connected.return_value = [
            _annotated(list_open_tickets, readOnlyHint=True),
            create_ticket,
            _annotated(purge_queue, readOnlyHint=True, destructiveHint=True),
            _annotated(fetch_digest, readOnlyHint=False),
        ]

        result = await scout_tools(USER_ID, CUSTOM_MCP)

        assert list(result.read_only) == ["list_open_tickets"]
        assert (result.total, result.fingerprint) == (
            4,
            tool_fingerprint([list_open_tickets, create_ticket, purge_queue, fetch_digest]),
        )

    @pytest.mark.regression
    @pytest.mark.usefixtures("native")
    async def test_a_composio_tool_without_its_read_only_tag_is_never_a_scouts(self) -> None:
        """GitHub handed scouts accept-invitation and follow-user; Todoist close and reopen."""
        result = await scout_tools(USER_ID, "linear")

        assert list(result.read_only) == ["list_open_tickets"]

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


def _many(count: int) -> dict[str, BaseTool]:
    return {
        f"get_{n}": list_open_tickets.model_copy(update={"name": f"get_{n}"}) for n in range(count)
    }


class _Store:
    """The tool index: answers a search with a fixed ranking, and remembers what it was asked."""

    def __init__(self, ranked: list[str]) -> None:
        self.ranked = ranked
        self.searches: list[tuple[tuple[str, ...], str, int]] = []

    async def asearch(self, namespace: tuple[str, ...], *, query: str, limit: int) -> list:
        self.searches.append((namespace, query, limit))
        return [SimpleNamespace(key=name) for name in self.ranked]


class TestBoundTools:
    async def test_under_the_ceiling_every_read_only_tool_is_bound(self) -> None:
        read_only = _many(3)

        bound = await bound_tools(ScoutTools("linear", read_only, total=9, fingerprint="f"))

        assert bound == read_only

    @pytest.mark.regression
    async def test_past_the_ceiling_the_index_picks_the_most_relevant_read_only_tools(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GitHub bound its first 100 tools alphabetically and never saw notifications."""
        read_only = _many(SCOUT_MAX_BOUND_TOOLS + 20)
        ranked = ["create_x", "get_119", "get_7", *[f"get_{n}" for n in range(200)]]
        store = _Store(ranked)
        monkeypatch.setattr(scout_tools_module, "get_tools_store", AsyncMock(return_value=store))
        monkeypatch.setattr(
            scout_tools_module, "get_subagent_by_id", {"github": _subagent("composio")}.get
        )

        bound = await bound_tools(ScoutTools("github", read_only, total=899, fingerprint="f"))

        assert list(bound)[:3] == ["get_119", "get_7", "get_0"]
        assert len(bound) == SCOUT_MAX_BOUND_TOOLS
        assert "create_x" not in bound
        assert store.searches == [(("composio-space",), SCOUT_TOOL_QUERY, 899)]

    async def test_a_custom_mcp_is_searched_under_its_url_namespace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _Store([f"get_{n}" for n in range(SCOUT_MAX_BOUND_TOOLS + 1)])
        resolved = SimpleNamespace(mcp_config=SimpleNamespace(server_url="https://mcp.acme.io/mcp"))
        monkeypatch.setattr(scout_tools_module, "get_tools_store", AsyncMock(return_value=store))
        monkeypatch.setattr(scout_tools_module, "get_subagent_by_id", {}.get)
        monkeypatch.setattr(
            scout_tools_module.IntegrationResolver, "resolve", AsyncMock(return_value=resolved)
        )
        monkeypatch.setattr(
            scout_tools_module,
            "derive_integration_namespace",
            lambda iid, url, is_custom: f"{iid}|{url}|{is_custom}",
        )

        await bound_tools(
            ScoutTools(CUSTOM_MCP, _many(SCOUT_MAX_BOUND_TOOLS + 1), total=150, fingerprint="f")
        )

        assert store.searches[0][0] == (f"{CUSTOM_MCP}|https://mcp.acme.io/mcp|True",)

    async def test_an_index_that_ranks_none_of_them_fails_loud(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            scout_tools_module, "get_tools_store", AsyncMock(return_value=_Store(["create_x"]))
        )
        monkeypatch.setattr(
            scout_tools_module, "get_subagent_by_id", {"github": _subagent("composio")}.get
        )

        with pytest.raises(AppError) as raised:
            await bound_tools(
                ScoutTools("github", _many(SCOUT_MAX_BOUND_TOOLS + 1), total=300, fingerprint="f")
            )

        assert raised.value.message == "the tool index ranks none of github's read-only tools"
