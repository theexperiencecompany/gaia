"""Unit tests for activate_integration — tool registration + context injection."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_MOD = "app.agents.core.subagents.integration_activation"


def _subagent(
    agent_name: str = "gmail_agent",
    managed_by: str = "composio",
    requires_auth: bool = False,
) -> MagicMock:
    subagent = MagicMock()
    subagent.config.agent_name = agent_name
    subagent.managed_by = managed_by
    subagent.mcp_config = MagicMock(requires_auth=requires_auth) if managed_by == "mcp" else None
    return subagent


class TestActivationContext:
    async def test_assembles_prompt_instructions_and_skills(self, monkeypatch) -> None:
        from app.agents.core.subagents.integration_activation import _activation_context

        monkeypatch.setattr(
            f"{_MOD}.build_subagent_system_prompt", AsyncMock(return_value="You manage gmail.")
        )
        monkeypatch.setattr(f"{_MOD}.get_subagent_by_id", lambda _: _subagent())
        monkeypatch.setattr(f"{_MOD}.get_instructions", AsyncMock(return_value="Always CC me."))
        monkeypatch.setattr(
            f"{_MOD}.get_available_skills_text", AsyncMock(return_value="- gmail-draft-send")
        )
        monkeypatch.setattr(f"{_MOD}.integration_skills_block", lambda _: "")

        context = await _activation_context("gmail", "u1")
        assert "You manage gmail." in context
        assert "Always CC me." in context
        assert "gmail-draft-send" in context

    async def test_empty_everywhere_yields_empty_context(self, monkeypatch) -> None:
        from app.agents.core.subagents.integration_activation import _activation_context

        monkeypatch.setattr(f"{_MOD}.build_subagent_system_prompt", AsyncMock(return_value=""))
        monkeypatch.setattr(f"{_MOD}.get_subagent_by_id", lambda _: None)
        monkeypatch.setattr(f"{_MOD}.integration_skills_block", lambda _: "")
        assert await _activation_context("gmail", None) == ""

    async def test_enrichment_failure_degrades_to_partial_not_raise(self, monkeypatch) -> None:
        """A transient store failure mid-enrichment must not abort activation.

        The tools are already registered and bound by the time this runs, so a
        failed instructions/skills lookup degrades to the sections gathered so
        far rather than propagating and failing the whole tool call.
        """
        from app.agents.core.subagents.integration_activation import _activation_context

        monkeypatch.setattr(
            f"{_MOD}.build_subagent_system_prompt", AsyncMock(return_value="You manage gmail.")
        )
        monkeypatch.setattr(f"{_MOD}.get_subagent_by_id", lambda _: _subagent())
        monkeypatch.setattr(
            f"{_MOD}.get_instructions", AsyncMock(side_effect=ConnectionError("mongo down"))
        )
        monkeypatch.setattr(f"{_MOD}.integration_skills_block", lambda _: "")

        context = await _activation_context("gmail", "u1")
        # The section gathered before the failure survives; the call does not raise.
        assert "You manage gmail." in context


class TestActivateTools:
    async def test_counts_tools_in_the_registered_category(self, monkeypatch) -> None:
        from app.agents.core.subagents.integration_activation import _activate_tools

        registry = MagicMock()
        registry.get_category.return_value = MagicMock(tools=[MagicMock(), MagicMock()])
        monkeypatch.setattr(
            f"{_MOD}.register_integration_tools", AsyncMock(return_value="gmail_toolkit")
        )
        monkeypatch.setattr(f"{_MOD}.get_tool_registry", AsyncMock(return_value=registry))

        total, bind = await _activate_tools(_subagent())
        assert total == 2
        assert bind == []
        registry.get_category.assert_called_once_with("gmail_toolkit")

    async def test_no_category_means_no_integration_tools(self, monkeypatch) -> None:
        """Internal integrations ride on core tools — nothing category-specific loads."""
        from app.agents.core.subagents.integration_activation import _activate_tools

        monkeypatch.setattr(f"{_MOD}.register_integration_tools", AsyncMock(return_value=None))
        get_registry = AsyncMock()
        monkeypatch.setattr(f"{_MOD}.get_tool_registry", get_registry)

        registry = MagicMock()
        registry.get_tool_meta.return_value = None
        get_registry.return_value = registry

        total, bind = await _activate_tools(_subagent(managed_by="internal"))
        assert (total, bind) == (0, [])
        registry.get_category.assert_not_called()


class TestAutoBind:
    """Parity with the integration's own subagent, which gets these pre-bound at
    startup. Without them activation costs an extra retrieve_tools turn."""

    @staticmethod
    def _registry(known: set[str]) -> MagicMock:
        registry = MagicMock()
        registry.get_category.return_value = MagicMock(tools=[MagicMock()] * 40)
        registry.get_tool_meta.side_effect = lambda n: MagicMock() if n in known else None
        return registry

    async def test_binds_auto_bind_plus_extra_initial_tools(self, monkeypatch) -> None:
        from app.agents.core.subagents.integration_activation import _activate_tools

        subagent = _subagent()
        subagent.config.auto_bind_tools = ["GMAIL_FETCH_MESSAGES", "GMAIL_FETCH_THREAD"]
        subagent.config.extra_initial_tools = ["query_json", "grep"]
        known = {"GMAIL_FETCH_MESSAGES", "GMAIL_FETCH_THREAD", "query_json", "grep"}

        monkeypatch.setattr(f"{_MOD}.register_integration_tools", AsyncMock(return_value="GMAIL"))
        monkeypatch.setattr(
            f"{_MOD}.get_tool_registry", AsyncMock(return_value=self._registry(known))
        )

        total, bind = await _activate_tools(subagent)
        assert total == 40
        assert bind == ["GMAIL_FETCH_MESSAGES", "GMAIL_FETCH_THREAD", "query_json", "grep"]

    async def test_drops_names_the_registry_does_not_hold(self, monkeypatch) -> None:
        """An unregistered name is silently ignored at bind time, so reporting it
        as bound would tell the model it can call something it cannot."""
        from app.agents.core.subagents.integration_activation import _activate_tools

        subagent = _subagent()
        subagent.config.auto_bind_tools = ["GMAIL_FETCH_MESSAGES", "GMAIL_GHOST_TOOL"]
        subagent.config.extra_initial_tools = None

        monkeypatch.setattr(f"{_MOD}.register_integration_tools", AsyncMock(return_value="GMAIL"))
        monkeypatch.setattr(
            f"{_MOD}.get_tool_registry",
            AsyncMock(return_value=self._registry({"GMAIL_FETCH_MESSAGES"})),
        )

        _, bind = await _activate_tools(subagent)
        assert bind == ["GMAIL_FETCH_MESSAGES"]


class TestActivateIntegrationTool:
    @staticmethod
    def _invoke(configurable: dict | None = None, **kwargs) -> tuple[dict, dict]:
        return (
            {"args": kwargs, "name": "activate_integration", "type": "tool_call", "id": "call1"},
            {"configurable": configurable or {}},
        )

    @staticmethod
    def _text(command) -> str:
        return str(command.update["messages"][0].content)

    @staticmethod
    def _bound(command) -> list[str]:
        return list(command.update.get("selected_tool_ids") or [])

    @pytest.fixture(autouse=True)
    def _enable_flag(self, monkeypatch):
        from app.config.settings import settings

        monkeypatch.setattr(settings, "ENABLE_INTEGRATION_ACTIVATION", True)

    async def test_disabled_flag_short_circuits(self, monkeypatch) -> None:
        from app.agents.core.subagents.integration_activation import activate_integration
        from app.config.settings import settings

        monkeypatch.setattr(settings, "ENABLE_INTEGRATION_ACTIVATION", False)
        call, run_cfg = self._invoke({}, integration_id="gmail")
        result = await activate_integration.ainvoke(call, run_cfg)
        assert "disabled" in self._text(result)

    async def test_unknown_integration_fails_loud(self) -> None:
        from app.agents.core.subagents.integration_activation import activate_integration

        with patch(f"{_MOD}._get_subagent_by_id", new=AsyncMock(return_value=None)):
            call, run_cfg = self._invoke({}, integration_id="nope")
            result = await activate_integration.ainvoke(call, run_cfg)
        assert "Unknown integration" in self._text(result)

    async def test_registers_tools_and_returns_expertise(self) -> None:
        from app.agents.core.subagents.integration_activation import activate_integration

        with (
            patch(f"{_MOD}._get_subagent_by_id", new=AsyncMock(return_value=_subagent())),
            patch(f"{_MOD}.check_integration_connection", new=AsyncMock(return_value=None)),
            patch(f"{_MOD}._activate_tools", new=AsyncMock(return_value=(7, []))) as activate_tools,
            patch(f"{_MOD}._activation_context", new=AsyncMock(return_value="PROMPT + SKILLS")),
        ):
            call, run_cfg = self._invoke({"user_id": "u1"}, integration_id="gmail")
            result = await activate_integration.ainvoke(call, run_cfg)

        activate_tools.assert_awaited_once()
        assert "PROMPT + SKILLS" in self._text(result)
        assert "7 tools" in self._text(result)

    async def test_unconnected_integration_returns_the_connect_prompt(self) -> None:
        """Activating an unconnected integration must gate on the connection check.

        That check is what renders the connect card. Registering its tools anyway
        would bind tools that fail at call time with an auth error, and the user
        would never see a button.
        """
        from app.agents.core.subagents.integration_activation import activate_integration

        connect = AsyncMock(return_value="Connect your Gmail account to continue.")
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

    async def test_internal_integration_skips_the_connection_check(self) -> None:
        """Built-ins (todos, reminders) have no account to connect."""
        from app.agents.core.subagents.integration_activation import activate_integration

        connect = AsyncMock()
        with (
            patch(
                f"{_MOD}._get_subagent_by_id",
                new=AsyncMock(return_value=_subagent(managed_by="internal")),
            ),
            patch(f"{_MOD}.check_integration_connection", new=connect),
            patch(f"{_MOD}._activate_tools", new=AsyncMock(return_value=(0, []))),
            patch(f"{_MOD}._activation_context", new=AsyncMock(return_value="")),
        ):
            call, run_cfg = self._invoke({"user_id": "u1"}, integration_id="todos")
            result = await activate_integration.ainvoke(call, run_cfg)

        connect.assert_not_awaited()
        assert "is now active" in self._text(result)

    async def test_per_user_mcp_integration_routes_to_handoff(self) -> None:
        """Its tools live only in the caller's MCP session, so activation cannot bind
        them. Instead of dead-ending, it points the model at handoff, which runs the
        integration in its own per-user graph.
        """
        from app.agents.core.subagents.integration_activation import activate_integration

        with (
            patch(
                f"{_MOD}._get_subagent_by_id",
                new=AsyncMock(return_value=_subagent(managed_by="mcp", requires_auth=True)),
            ),
            patch(f"{_MOD}._activate_tools", new=AsyncMock()) as activate_tools,
        ):
            call, run_cfg = self._invoke({"user_id": "u1"}, integration_id="perplexity")
            result = await activate_integration.ainvoke(call, run_cfg)

        activate_tools.assert_not_awaited()
        text = self._text(result)
        assert "handoff(" in text and "per-user" in text

    async def test_custom_mcp_dict_routes_to_handoff(self) -> None:
        """A custom MCP integration resolves as a dict (from the repository), not a
        registry Subagent. It is per-user, so it routes to handoff too."""
        from app.agents.core.subagents.integration_activation import activate_integration

        custom = {"id": "abc123", "name": "My MCP", "managed_by": "mcp", "mcp_config": {}}
        with (
            patch(f"{_MOD}._get_subagent_by_id", new=AsyncMock(return_value=custom)),
            patch(f"{_MOD}._activate_tools", new=AsyncMock()) as activate_tools,
        ):
            call, run_cfg = self._invoke({"user_id": "u1"}, integration_id="abc123")
            result = await activate_integration.ainvoke(call, run_cfg)

        activate_tools.assert_not_awaited()
        text = self._text(result)
        assert "handoff(" in text and "per-user" in text

    async def test_non_auth_mcp_integration_activates(self) -> None:
        from app.agents.core.subagents.integration_activation import activate_integration

        with (
            patch(
                f"{_MOD}._get_subagent_by_id",
                new=AsyncMock(return_value=_subagent(managed_by="mcp", requires_auth=False)),
            ),
            patch(f"{_MOD}._activate_tools", new=AsyncMock(return_value=(3, []))),
            patch(f"{_MOD}._activation_context", new=AsyncMock(return_value="")),
        ):
            call, run_cfg = self._invoke({"user_id": "u1"}, integration_id="deepwiki")
            result = await activate_integration.ainvoke(call, run_cfg)

        assert "3 tools" in self._text(result)


def test_tool_exports() -> None:
    from app.agents.core.subagents import integration_activation

    assert integration_activation.tools == [integration_activation.activate_integration]
