"""Unit tests for activate_integration — tool registration + context injection."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.tools import tool as langchain_tool
from langgraph.types import Command
import pytest

from app.agents.core.subagents import integration_activation
from app.agents.core.subagents.handoff_tools import CustomMcpSubagent
from app.agents.core.subagents.integration_activation import (
    _activate_tools,
    _activation_context,
    _activation_header,
    activate_integration,
)
from app.agents.tools.execute.resolver import ResolvedTool
from app.constants.log_tags import LogTag
from tests.helpers import captured_wide_event

_MOD = "app.agents.core.subagents.integration_activation"

#: What the reply says in place of context when enrichment gathered nothing.
NO_CONTEXT = "(no additional context available)"
SPAWN_LINE = "Anything you spawn inherits the bound tools."
REFRAME = (
    "The notes below describe this integration's tools, conventions, "
    "and standing rules — follow those. They were written for a "
    "delegated worker, which you are not: you are the executor, "
    "acting on this integration yourself in your own turn. IGNORE "
    "any instruction about receiving a delegated task, reporting "
    "to a parent, or calling finish_task (never call it — reply "
    "normally when the work is done)."
)


def _subagent(
    agent_name: str = "gmail_agent",
    managed_by: str = "composio",
    requires_auth: bool = False,
) -> MagicMock:
    subagent = MagicMock()
    subagent.id = "gmail"
    subagent.config.agent_name = agent_name
    subagent.managed_by = managed_by
    subagent.mcp_config = MagicMock(requires_auth=requires_auth) if managed_by == "mcp" else None
    return subagent


class TestActivationContext:
    @pytest.fixture
    def sources(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
        """Patch every enrichment source to answer; tests blank the ones they do not need."""
        mocks: dict[str, MagicMock] = {
            "build_subagent_system_prompt": AsyncMock(return_value="You manage gmail."),
            "get_instructions": AsyncMock(return_value="Always CC me."),
            "build_provider_metadata_block": AsyncMock(
                return_value="USER CONTEXT FOR GMAIL:\n- email: me@x.com"
            ),
            "get_subagent_by_id": MagicMock(return_value=_subagent()),
            "get_available_skills_text": AsyncMock(return_value="- gmail-draft-send"),
            "integration_skills_block": MagicMock(return_value="## Workspace skills\n- triage"),
        }
        for name, mock in mocks.items():
            monkeypatch.setattr(f"{_MOD}.{name}", mock)
        return mocks

    async def test_every_section_lands_in_order_for_this_integration_and_user(
        self, sources: dict[str, MagicMock]
    ) -> None:
        context = await _activation_context("gmail", "u1")

        assert context == "\n\n".join(
            [
                f"## gmail: how it works\n{REFRAME}\nYou manage gmail.",
                "## The user's standing instructions for gmail\nAlways CC me.",
                "USER CONTEXT FOR GMAIL:\n- email: me@x.com",
                "## gmail skills available to read on demand\n- gmail-draft-send",
                "## Workspace skills\n- triage",
            ]
        )
        sources["build_subagent_system_prompt"].assert_awaited_once_with(integration_id="gmail")
        sources["get_instructions"].assert_awaited_once_with("u1", "gmail")
        sources["build_provider_metadata_block"].assert_awaited_once_with("gmail", "u1")
        sources["get_subagent_by_id"].assert_called_once_with("gmail")
        sources["get_available_skills_text"].assert_awaited_once_with("u1", "gmail_agent")
        sources["integration_skills_block"].assert_called_once_with("gmail")

    async def test_an_unknown_subagent_still_lists_skills_under_no_agent_name(
        self, sources: dict[str, MagicMock]
    ) -> None:
        sources["get_subagent_by_id"].return_value = None

        await _activation_context("gmail", "u1")

        sources["get_available_skills_text"].assert_awaited_once_with("u1", "")

    async def test_empty_everywhere_yields_empty_context(
        self, sources: dict[str, MagicMock]
    ) -> None:
        sources["build_subagent_system_prompt"].return_value = ""
        sources["integration_skills_block"].return_value = ""

        assert await _activation_context("gmail", None) == ""
        sources["get_instructions"].assert_not_awaited()

    async def test_enrichment_failure_degrades_to_partial_and_is_logged(
        self, sources: dict[str, MagicMock]
    ) -> None:
        """A transient store failure mid-enrichment must not abort activation."""
        sources["get_instructions"].side_effect = ConnectionError("mongo down")

        async with captured_wide_event() as event:
            context = await _activation_context("gmail", "u1")

        assert context == f"## gmail: how it works\n{REFRAME}\nYou manage gmail."
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.AGENT} Activation context enrichment failed; degrading to partial",
                "integration": "gmail",
                "error_type": "ConnectionError",
                "error": "mongo down",
            }
        ]


class TestActivateTools:
    async def test_counts_tools_in_the_registered_category(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry = MagicMock()
        registry.get_category.return_value = MagicMock(tools=[MagicMock(), MagicMock()])
        register = AsyncMock(return_value="gmail_toolkit")
        monkeypatch.setattr(f"{_MOD}.register_integration_tools", register)
        monkeypatch.setattr(f"{_MOD}.get_tool_registry", AsyncMock(return_value=registry))
        subagent = _subagent()

        total, bind, preloaded, docs = await _activate_tools(subagent)

        assert (total, bind, preloaded, docs) == (2, [], [], "")
        register.assert_awaited_once_with(subagent)
        registry.get_category.assert_called_once_with("gmail_toolkit")

    async def test_a_category_the_registry_cannot_find_counts_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry = MagicMock()
        registry.get_category.return_value = None
        monkeypatch.setattr(
            f"{_MOD}.register_integration_tools", AsyncMock(return_value="gmail_toolkit")
        )
        monkeypatch.setattr(f"{_MOD}.get_tool_registry", AsyncMock(return_value=registry))

        total, *_ = await _activate_tools(_subagent())

        assert total == 0

    async def test_no_category_means_no_integration_tools(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Internal integrations ride on core tools — nothing category-specific loads."""
        registry = MagicMock()
        registry.get_tool_meta.return_value = None
        monkeypatch.setattr(f"{_MOD}.register_integration_tools", AsyncMock(return_value=None))
        monkeypatch.setattr(f"{_MOD}.get_tool_registry", AsyncMock(return_value=registry))

        total, bind, preloaded, docs = await _activate_tools(_subagent(managed_by="internal"))

        assert (total, bind, preloaded, docs) == (0, [], [], "")
        registry.get_category.assert_not_called()

    async def test_the_split_and_the_docs_are_resolved_for_this_user(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        subagent = _subagent()
        subagent.config.auto_bind_tools = ["GMAIL_FETCH_MESSAGES"]
        subagent.config.extra_initial_tools = ["query_json"]
        registry = MagicMock()
        split = AsyncMock(return_value=(["query_json"], ["GMAIL_FETCH_MESSAGES"]))
        render = AsyncMock(return_value="DOCS")
        monkeypatch.setattr(f"{_MOD}.register_integration_tools", AsyncMock(return_value=None))
        monkeypatch.setattr(f"{_MOD}.get_tool_registry", AsyncMock(return_value=registry))
        monkeypatch.setattr(f"{_MOD}.split_startup_tools", split)
        monkeypatch.setattr(f"{_MOD}.render_preload_block", render)

        async with captured_wide_event() as event:
            result = await _activate_tools(subagent, "u1")

        assert result == (0, ["query_json"], ["GMAIL_FETCH_MESSAGES"], "DOCS")
        split.assert_awaited_once_with("u1", ["GMAIL_FETCH_MESSAGES", "query_json"])
        render.assert_awaited_once_with("u1", ["GMAIL_FETCH_MESSAGES"])
        assert "warnings" not in event


def _split_registry(known: set[str], integration_names: set[str]) -> MagicMock:
    """Build a registry mock that classifies integration_names as execute-routed."""
    registry = MagicMock()
    registry.get_tool_meta.side_effect = lambda n: MagicMock() if n in known else None
    registry.get_category_of_tool.side_effect = (
        lambda n: "int_cat" if n in integration_names else "general"
    )

    def _get_category(name: str) -> MagicMock:
        category = MagicMock(tools=[MagicMock()] * 40)
        category.require_integration = name == "int_cat"
        return category

    registry.get_category.side_effect = _get_category
    return registry


def _resolved_tool(name: str) -> ResolvedTool:
    """Build a resolvable fake integration tool with a real renderable schema."""

    @langchain_tool
    def _fake(query: str) -> str:
        """Run a fake query."""
        return query

    _fake.name = name
    return ResolvedTool(name=name, tool=_fake, is_integration=True)


class TestAutoBind:
    """Parity with the integration's own subagent, which preloads these as schema docs at startup.

    Activation binds the internal helpers and documents the integration tools — binding an
    integration tool here would reintroduce the provider-side binding the proxy exists to remove.
    """

    @staticmethod
    def _patch_registries(monkeypatch: pytest.MonkeyPatch, registry: MagicMock) -> None:
        monkeypatch.setattr(f"{_MOD}.register_integration_tools", AsyncMock(return_value="GMAIL"))
        monkeypatch.setattr(f"{_MOD}.get_tool_registry", AsyncMock(return_value=registry))
        monkeypatch.setattr(
            "app.agents.tools.core.retrieval.get_tool_registry",
            AsyncMock(return_value=registry),
        )

    @pytest.mark.usefixtures("no_observed_tool_shapes")
    async def test_splits_bind_helpers_from_preloaded_integration_tools(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        subagent = _subagent()
        subagent.config.auto_bind_tools = ["GMAIL_FETCH_MESSAGES", "GMAIL_FETCH_THREAD"]
        subagent.config.extra_initial_tools = ["query_json", "grep"]
        known = {"GMAIL_FETCH_MESSAGES", "GMAIL_FETCH_THREAD", "query_json", "grep"}
        integration = {"GMAIL_FETCH_MESSAGES", "GMAIL_FETCH_THREAD"}

        self._patch_registries(monkeypatch, _split_registry(known, integration))
        monkeypatch.setattr(
            "app.agents.tools.core.retrieval._resolve_for_retrieval",
            AsyncMock(side_effect=lambda _u, n: _resolved_tool(n)),
        )

        total, bind, preloaded, docs = await _activate_tools(subagent)
        assert total == 40
        assert bind == ["query_json", "grep"]
        assert preloaded == ["GMAIL_FETCH_MESSAGES", "GMAIL_FETCH_THREAD"]
        assert "## GMAIL_FETCH_MESSAGES" in docs
        assert "## GMAIL_FETCH_THREAD" in docs
        assert "NOT bound" in docs

    @pytest.mark.usefixtures("no_observed_tool_shapes")
    async def test_drops_names_the_registry_does_not_hold(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unregistered name is silently ignored at bind time, so reporting it as bound would tell the model it can call something it cannot."""
        subagent = _subagent()
        subagent.config.auto_bind_tools = ["GMAIL_FETCH_MESSAGES", "GMAIL_GHOST_TOOL"]
        subagent.config.extra_initial_tools = None

        self._patch_registries(
            monkeypatch, _split_registry({"GMAIL_FETCH_MESSAGES"}, {"GMAIL_FETCH_MESSAGES"})
        )
        monkeypatch.setattr(
            "app.agents.tools.core.retrieval._resolve_for_retrieval",
            AsyncMock(side_effect=lambda _u, n: _resolved_tool(n)),
        )

        async with captured_wide_event() as event:
            _, bind, preloaded, _ = await _activate_tools(subagent)

        assert bind == []
        assert preloaded == ["GMAIL_FETCH_MESSAGES"]
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.AGENT} Activation dropped unregistered startup tools",
                "integration": "gmail",
                "dropped_tools": ["GMAIL_GHOST_TOOL"],
            }
        ]

    async def test_unrenderable_preload_warns_instead_of_binding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When docs cannot render, the tool is reported — not silently bound behind the proxy's back."""
        subagent = _subagent()
        subagent.config.auto_bind_tools = ["GMAIL_FETCH_MESSAGES"]
        subagent.config.extra_initial_tools = None

        self._patch_registries(
            monkeypatch, _split_registry({"GMAIL_FETCH_MESSAGES"}, {"GMAIL_FETCH_MESSAGES"})
        )
        monkeypatch.setattr(
            "app.agents.tools.core.retrieval._resolve_for_retrieval",
            AsyncMock(return_value=None),
        )

        async with captured_wide_event() as event:
            _, bind, preloaded, docs = await _activate_tools(subagent)

        assert bind == []
        assert preloaded == ["GMAIL_FETCH_MESSAGES"]
        assert docs == ""
        assert {
            "msg": f"{LogTag.AGENT} Activation preloaded tools but rendered no docs",
            "integration": "gmail",
            "preloaded": ["GMAIL_FETCH_MESSAGES"],
        } in event["warnings"]


class TestActivationHeader:
    """The reply's lead tells the model exactly which of three retrieve paths works this run."""

    PRELOAD_NOTE = (
        "1 integration tool(s) are preloaded in the schemas section at the end of this "
        "message — NOT bound, do NOT call them by name. Run them "
        'with execute(task_description="...", tool_name="<NAME>", data={...}) '
        "built from those schemas."
    )

    def test_bound_helpers_and_a_searchable_preload(self) -> None:
        header = _activation_header("gmail", 40, ["query_json", "grep"], ["GMAIL_X"], "D", True)

        assert header == (
            "Integration 'gmail' is now active with 40 tools. "
            "2 helper tool(s) are ALREADY BOUND and callable right now: query_json, grep. "
            f"Call those directly. {self.PRELOAD_NOTE} retrieve_tools searches gmail too, so "
            f"use it if you need one of the other 37. {SPAWN_LINE}\n\n"
        )

    def test_the_remaining_count_never_goes_negative(self) -> None:
        header = _activation_header("gmail", 1, [], ["GMAIL_X"], "D", True)

        assert "one of the other 0." in header

    def test_an_unstamped_preload_asks_for_exact_names(self) -> None:
        header = _activation_header("gmail", 40, [], ["GMAIL_X"], "D", False)

        assert header == (
            f"Integration 'gmail' is now active with 40 tools. {self.PRELOAD_NOTE} "
            "retrieve_tools query search does not cover this integration in this run — pass "
            "exact tool names from the schemas above instead of searching for them. "
            f"{SPAWN_LINE}\n\n"
        )

    def test_a_preload_that_rendered_no_docs_is_not_described_as_preloaded(self) -> None:
        header = _activation_header("gmail", 40, [], ["GMAIL_X"], "", True)

        assert header == (
            "Integration 'gmail' is now active with 40 tools. "
            f"Use retrieve_tools to bind the ones this task needs. {SPAWN_LINE}\n\n"
        )

    def test_bound_helpers_alone_need_no_retrieve_guidance(self) -> None:
        header = _activation_header("gmail", 40, ["query_json"], [], "", True)

        assert header == (
            "Integration 'gmail' is now active with 40 tools. "
            "1 helper tool(s) are ALREADY BOUND and callable right now: query_json. "
            f"Call those directly. {SPAWN_LINE}\n\n"
        )

    def test_an_unstamped_activation_asks_for_exact_names(self) -> None:
        header = _activation_header("gmail", 40, [], [], "", False)

        assert header == (
            "Integration 'gmail' is now active with 40 tools. Use retrieve_tools with exact "
            "tool names to bind the ones this task needs — query search does not cover this "
            f"integration in this run. {SPAWN_LINE}\n\n"
        )

    def test_nothing_registered_points_away_from_retrieve_tools(self) -> None:
        header = _activation_header("todos", 0, [], [], "", False)

        assert header == (
            "Integration 'todos' is now active with 0 tools. It registered no tools of its own "
            "— everything it offers is in the context above. Use retrieve_tools only for "
            f"unrelated needs. {SPAWN_LINE}\n\n"
        )

    def test_zero_tools_with_an_undocumented_preload_is_not_called_empty(self) -> None:
        header = _activation_header("gmail", 0, [], ["GMAIL_X"], "", False)

        assert "It registered no tools of its own" not in header
        assert "Use retrieve_tools with exact tool names" in header


class TestActivateIntegrationTool:
    @staticmethod
    def _invoke(configurable: dict | None = None, **kwargs: str) -> tuple[dict, dict]:
        return (
            {"args": kwargs, "name": "activate_integration", "type": "tool_call", "id": "call1"},
            {"configurable": configurable or {}},
        )

    @staticmethod
    def _text(command: Command) -> str:
        return str(command.update["messages"][0].content)

    @staticmethod
    def _bound(command: Command) -> list[str]:
        return list(command.update.get("selected_tool_ids") or [])

    @pytest.fixture
    def connected(self) -> Iterator[AsyncMock]:
        """Resolve gmail as a connected composio integration."""
        resolve = AsyncMock(return_value=_subagent())
        with (
            patch(f"{_MOD}._get_subagent_by_id", new=resolve),
            patch(f"{_MOD}.check_integration_connection", new=AsyncMock(return_value=None)),
        ):
            yield resolve

    async def test_unknown_integration_fails_loud(self) -> None:
        resolve = AsyncMock(return_value=None)
        async with captured_wide_event() as event:
            with patch(f"{_MOD}._get_subagent_by_id", new=resolve):
                call, run_cfg = self._invoke({}, integration_id="nope")
                result = await activate_integration.ainvoke(call, run_cfg)

        assert self._text(result) == "Unknown integration 'nope'."
        resolve.assert_awaited_once_with("nope")
        assert event["activation"] == {"integration": "nope"}
        assert event["warnings"] == [
            {"msg": f"{LogTag.AGENT} Activation requested for unknown integration"}
        ]

    async def test_registers_tools_and_returns_expertise(self, connected: AsyncMock) -> None:
        activate_tools = AsyncMock(return_value=(7, [], [], ""))
        context = AsyncMock(return_value="PROMPT + SKILLS")
        async with captured_wide_event() as event:
            with (
                patch(f"{_MOD}._activate_tools", new=activate_tools),
                patch(f"{_MOD}._activation_context", new=context),
            ):
                call, run_cfg = self._invoke({"user_id": "u1"}, integration_id="gmail")
                result = await activate_integration.ainvoke(call, run_cfg)

        activate_tools.assert_awaited_once_with(connected.return_value, "u1")
        context.assert_awaited_once_with("gmail", "u1")
        assert self._text(result) == (
            _activation_header("gmail", 7, [], [], "", False) + "PROMPT + SKILLS"
        )
        assert event["activation"] == {
            "integration": "gmail",
            "tool_count": 7,
            "bound_now": 0,
            "preloaded": 0,
            "context_length": len("PROMPT + SKILLS"),
        }

    async def test_an_empty_context_says_so_and_docs_trail_the_reply(
        self, connected: AsyncMock
    ) -> None:
        with (
            patch(
                f"{_MOD}._activate_tools",
                new=AsyncMock(return_value=(40, ["query_json"], ["GMAIL_X"], "DOCS")),
            ),
            patch(f"{_MOD}._activation_context", new=AsyncMock(return_value="")),
            patch(f"{_MOD}.mark_active", new=AsyncMock()),
        ):
            call, run_cfg = self._invoke(
                {"user_id": "u1", "conversation_id": "c9"}, integration_id="gmail"
            )
            result = await activate_integration.ainvoke(call, run_cfg)

        assert self._text(result) == (
            _activation_header("gmail", 40, ["query_json"], ["GMAIL_X"], "DOCS", True)
            + f"{NO_CONTEXT}\n\nDOCS"
        )
        assert self._bound(result) == ["query_json"]

    async def test_reply_preloads_docs_and_binds_only_helpers(self, connected: AsyncMock) -> None:
        """The reply carries integration schemas as docs while selected_tool_ids holds only the internal helpers — an integration tool must never be both documented-as-unbound and bound."""
        docs = "2 integration tool(s) preloaded below.\n## GMAIL_FETCH_MESSAGES"
        with (
            patch(
                f"{_MOD}._activate_tools",
                new=AsyncMock(return_value=(40, ["query_json"], ["GMAIL_FETCH_MESSAGES"], docs)),
            ),
            patch(f"{_MOD}._activation_context", new=AsyncMock(return_value="CTX")),
        ):
            call, run_cfg = self._invoke({"user_id": "u1"}, integration_id="gmail")
            result = await activate_integration.ainvoke(call, run_cfg)

        text = self._text(result)
        assert "ALREADY BOUND" in text and "query_json" in text
        assert "NOT bound" in text
        assert "## GMAIL_FETCH_MESSAGES" in text
        # Schemas live in the trailing section, never interleaved with context.
        assert text.index("CTX") < text.index("## GMAIL_FETCH_MESSAGES")
        assert self._bound(result) == ["query_json"]

    async def test_unconnected_integration_returns_the_connect_prompt(self) -> None:
        """Activating an unconnected integration must gate on the connection check."""
        connect = AsyncMock(return_value="Connect your Gmail account to continue.")
        async with captured_wide_event() as event:
            with (
                patch(f"{_MOD}._get_subagent_by_id", new=AsyncMock(return_value=_subagent())),
                patch(f"{_MOD}.check_integration_connection", new=connect),
                patch(f"{_MOD}._activate_tools", new=AsyncMock()) as activate_tools,
            ):
                call, run_cfg = self._invoke({"user_id": "u1"}, integration_id="gmail")
                result = await activate_integration.ainvoke(call, run_cfg)

        connect.assert_awaited_once_with("gmail", "u1")
        activate_tools.assert_not_awaited()
        assert self._text(result) == "Connect your Gmail account to continue."
        assert event["activation"] == {"integration": "gmail", "connected": False}

    async def test_internal_integration_skips_the_connection_check(self) -> None:
        """Built-ins (todos, reminders) have no account to connect."""
        connect = AsyncMock()
        with (
            patch(
                f"{_MOD}._get_subagent_by_id",
                new=AsyncMock(return_value=_subagent(managed_by="internal")),
            ),
            patch(f"{_MOD}.check_integration_connection", new=connect),
            patch(f"{_MOD}._activate_tools", new=AsyncMock(return_value=(0, [], [], ""))),
            patch(f"{_MOD}._activation_context", new=AsyncMock(return_value="")),
        ):
            call, run_cfg = self._invoke({"user_id": "u1"}, integration_id="todos")
            result = await activate_integration.ainvoke(call, run_cfg)

        connect.assert_not_awaited()
        assert "is now active" in self._text(result)

    @pytest.mark.parametrize(
        "resolved",
        [
            _subagent(managed_by="mcp", requires_auth=True),
            CustomMcpSubagent.model_validate(
                {"id": "abc123", "name": "My MCP", "managed_by": "mcp", "mcp_config": {}}
            ),
        ],
        ids=["auth-required-mcp", "custom-mcp"],
    )
    async def test_a_per_user_integration_routes_to_handoff(self, resolved: object) -> None:
        """Its tools live only in the caller's MCP session, so activation cannot bind them."""
        async with captured_wide_event() as event:
            with (
                patch(f"{_MOD}._get_subagent_by_id", new=AsyncMock(return_value=resolved)),
                patch(f"{_MOD}._activate_tools", new=AsyncMock()) as activate_tools,
            ):
                call, run_cfg = self._invoke({"user_id": "u1"}, integration_id="perplexity")
                result = await activate_integration.ainvoke(call, run_cfg)

        activate_tools.assert_not_awaited()
        assert self._text(result) == (
            "'perplexity' is a per-user integration, so its tools cannot be activated "
            "in-context. Delegate it with handoff(subagent_id='perplexity', task=...): that "
            "runs it in its own per-user graph and returns the result."
        )
        assert event["activation"] == {"integration": "perplexity", "routed_to_handoff": True}

    async def test_non_auth_mcp_integration_activates(self) -> None:
        with (
            patch(
                f"{_MOD}._get_subagent_by_id",
                new=AsyncMock(return_value=_subagent(managed_by="mcp", requires_auth=False)),
            ),
            patch(f"{_MOD}._activate_tools", new=AsyncMock(return_value=(3, [], [], ""))),
            patch(f"{_MOD}._activation_context", new=AsyncMock(return_value="")),
        ):
            call, run_cfg = self._invoke({"user_id": "u1"}, integration_id="deepwiki")
            result = await activate_integration.ainvoke(call, run_cfg)

        assert "3 tools" in self._text(result)

    @pytest.mark.parametrize(
        "activated",
        [(40, [], [], ""), (0, ["query_json"], [], ""), (0, [], ["GMAIL_X"], "")],
        ids=["tools-only", "bound-only", "preloaded-only"],
    )
    async def test_anything_made_available_stamps_the_conversation(
        self, connected: AsyncMock, activated: tuple[int, list[str], list[str], str]
    ) -> None:
        """Discovery searches activated namespaces, so a success that yields tools must stamp — otherwise retrieve_tools stays blind to them."""
        mark = AsyncMock()
        with (
            patch(f"{_MOD}._activate_tools", new=AsyncMock(return_value=activated)),
            patch(f"{_MOD}._activation_context", new=AsyncMock(return_value="")),
            patch(f"{_MOD}.mark_active", new=mark),
        ):
            call, run_cfg = self._invoke(
                {"user_id": "u1", "conversation_id": "c9"}, integration_id="gmail"
            )
            await activate_integration.ainvoke(call, run_cfg)

        mark.assert_awaited_once_with("c9", "gmail")

    async def test_empty_activation_does_not_stamp(self, connected: AsyncMock) -> None:
        """Nothing became available — stamping would add a fruitless namespace search to every later discovery call in the conversation."""
        mark = AsyncMock()
        with (
            patch(f"{_MOD}._activate_tools", new=AsyncMock(return_value=(0, [], [], ""))),
            patch(f"{_MOD}._activation_context", new=AsyncMock(return_value="")),
            patch(f"{_MOD}.mark_active", new=mark),
        ):
            call, run_cfg = self._invoke({"user_id": "u1"}, integration_id="todos")
            await activate_integration.ainvoke(call, run_cfg)

        mark.assert_not_awaited()

    async def test_missing_conversation_id_skips_stamp(self, connected: AsyncMock) -> None:
        mark = AsyncMock()
        async with captured_wide_event() as event:
            with (
                patch(
                    f"{_MOD}._activate_tools",
                    new=AsyncMock(return_value=(40, [], ["GMAIL_X"], "DOCS")),
                ),
                patch(f"{_MOD}._activation_context", new=AsyncMock(return_value="")),
                patch(f"{_MOD}.mark_active", new=mark),
            ):
                call, run_cfg = self._invoke({"user_id": "u1"}, integration_id="gmail")
                result = await activate_integration.ainvoke(call, run_cfg)

        mark.assert_not_awaited()
        # The stamp is what makes "retrieve_tools searches gmail too" true —
        # without it the reply must not make that promise.
        assert "retrieve_tools searches gmail too" not in self._text(result)
        assert "exact tool names" in self._text(result)
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.AGENT} Activation stamp skipped: no conversation_id",
                "integration": "gmail",
            }
        ]

    async def test_stamped_activation_promises_namespace_search(self, connected: AsyncMock) -> None:
        with (
            patch(
                f"{_MOD}._activate_tools",
                new=AsyncMock(return_value=(40, [], ["GMAIL_X"], "DOCS")),
            ),
            patch(f"{_MOD}._activation_context", new=AsyncMock(return_value="")),
            patch(f"{_MOD}.mark_active", new=AsyncMock()),
        ):
            call, run_cfg = self._invoke(
                {"user_id": "u1", "conversation_id": "c9"}, integration_id="gmail"
            )
            result = await activate_integration.ainvoke(call, run_cfg)

        assert "retrieve_tools searches gmail too" in self._text(result)

    async def test_zero_tool_activation_does_not_point_at_retrieve_tools(
        self, connected: AsyncMock
    ) -> None:
        """Nothing registered — "use retrieve_tools" would send the model after tools that do not exist."""
        with (
            patch(f"{_MOD}._activate_tools", new=AsyncMock(return_value=(0, [], [], ""))),
            patch(f"{_MOD}._activation_context", new=AsyncMock(return_value="")),
            patch(f"{_MOD}.mark_active", new=AsyncMock()),
        ):
            call, run_cfg = self._invoke(
                {"user_id": "u1", "conversation_id": "c9"}, integration_id="todos"
            )
            result = await activate_integration.ainvoke(call, run_cfg)

        text = self._text(result)
        assert "0 tools" in text
        assert "Use retrieve_tools to bind" not in text


def test_tool_exports() -> None:
    assert integration_activation.tools == [integration_activation.activate_integration]
