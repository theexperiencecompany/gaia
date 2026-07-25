"""Tests for app/agents/middleware/subagent.py — SubagentMiddleware."""

from unittest.mock import AsyncMock, MagicMock

from langchain_core.tools import BaseTool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_middleware(**kwargs):
    """Create SubagentMiddleware with default test wiring."""
    from app.agents.middleware.subagent import SubagentMiddleware

    defaults = {
        "llm": None,
        "available_tools": [],
        "tool_registry": None,
        "max_turns": 5,
    }
    defaults.update(kwargs)
    return SubagentMiddleware(**defaults)


def _make_tool(name: str) -> MagicMock:
    """Create a mock BaseTool."""
    tool = MagicMock(spec=BaseTool)
    tool.name = name
    tool.ainvoke = AsyncMock(return_value=f"{name} result")
    return tool


def _make_config(user_id: str = "u1") -> dict:
    return {"configurable": {"user_id": user_id}}


# ---------------------------------------------------------------------------
# SubagentMiddleware.__init__
# ---------------------------------------------------------------------------


class TestSubagentMiddlewareInit:
    def test_default_init(self):
        mw = _make_middleware()
        assert mw._llm is None
        assert mw._available_tools == []
        assert "spawn_subagent" in mw._excluded_tools
        assert len(mw.tools) == 1  # spawn_subagent tool

    def test_excluded_tools_include_spawn_subagent(self):
        mw = _make_middleware(excluded_tool_names={"some_tool"})
        assert "spawn_subagent" in mw._excluded_tools
        assert "some_tool" in mw._excluded_tools

    def test_custom_tool_runtime_config(self):
        from app.agents.tools.core.tool_runtime_config import ToolRuntimeConfig

        config = ToolRuntimeConfig(
            initial_tool_names=["my_tool"],
            enable_retrieve_tools=False,
            include_subagents_in_retrieve=True,
        )
        mw = _make_middleware(tool_runtime_config=config)
        assert mw._tool_runtime_config.initial_tool_names == ["my_tool"]
        assert mw._tool_runtime_config.enable_retrieve_tools is False

    def test_default_tool_runtime_config(self):
        mw = _make_middleware()
        assert mw._tool_runtime_config.enable_retrieve_tools is True
        assert mw._tool_runtime_config.include_subagents_in_retrieve is False
        assert "read" in mw._tool_runtime_config.initial_tool_names


# ---------------------------------------------------------------------------
# set_llm / set_store / set_tools
# ---------------------------------------------------------------------------


class TestSetters:
    def test_set_llm(self):
        mw = _make_middleware()
        mock_llm = MagicMock()
        mock_llm.with_retry = MagicMock(return_value=mock_llm)
        mw.set_llm(mock_llm)
        assert mw._llm is mock_llm

    def test_set_store(self):
        mw = _make_middleware()
        mock_store = MagicMock()
        mw.set_store(mock_store)
        assert mw._store is mock_store

    def test_set_tools_updates_all(self):
        mw = _make_middleware()
        tools = [_make_tool("t1")]
        registry = {"r1": _make_tool("r1")}
        mw.set_tools(
            tools=tools,
            registry=registry,
            excluded_tool_names={"bad_tool"},
            tool_space="gmail",
        )
        assert mw._available_tools == tools
        assert mw._tool_registry == registry
        assert "bad_tool" in mw._excluded_tools
        assert "spawn_subagent" in mw._excluded_tools
        assert mw._tool_space == "gmail"

    def test_set_tools_partial(self):
        mw = _make_middleware()
        original_tools = mw._available_tools
        mw.set_tools(tool_space="slack")
        assert mw._tool_space == "slack"
        assert mw._available_tools is original_tools

    def test_set_tools_with_runtime_config(self):
        from app.agents.tools.core.tool_runtime_config import ToolRuntimeConfig

        mw = _make_middleware()
        new_config = ToolRuntimeConfig(initial_tool_names=["x"], enable_retrieve_tools=False)
        mw.set_tools(tool_runtime_config=new_config)
        assert mw._tool_runtime_config is new_config


# ---------------------------------------------------------------------------
# spawn_subagent tool (integration-style)
# ---------------------------------------------------------------------------


class TestSpawnSubagentTool:
    def test_tool_created(self):
        mw = _make_middleware()
        assert len(mw.tools) == 1
        tool = mw.tools[0]
        assert tool.name == "spawn_subagent"
