"""Tests for app/agents/middleware/subagent.py — SubagentMiddleware."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_middleware(**kwargs):
    """Create SubagentMiddleware with patched dependencies."""
    with patch(
        "app.agents.middleware.subagent.get_retrieve_tools_function",
        return_value=AsyncMock(return_value={"tools_to_bind": [], "response": []}),
    ):
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
        assert "vfs_read" in mw._tool_runtime_config.initial_tool_names


# ---------------------------------------------------------------------------
# set_llm / set_store / set_tools
# ---------------------------------------------------------------------------


class TestSetters:
    def test_set_llm(self):
        mw = _make_middleware()
        mock_llm = MagicMock()
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
        new_config = ToolRuntimeConfig(
            initial_tool_names=["x"], enable_retrieve_tools=False
        )
        mw.set_tools(tool_runtime_config=new_config)
        assert mw._tool_runtime_config is new_config


# ---------------------------------------------------------------------------
# _collect_tools
# ---------------------------------------------------------------------------


class TestCollectTools:
    def test_filters_excluded_tools(self):
        t1 = _make_tool("allowed")
        t2 = _make_tool("spawn_subagent")
        mw = _make_middleware(available_tools=[t1, t2])
        collected = mw._collect_tools()
        names = [t.name for t in collected]
        assert "allowed" in names
        assert "spawn_subagent" not in names

    def test_includes_registry_tools(self):
        t1 = _make_tool("from_avail")
        reg_tool = _make_tool("from_registry")
        mw = _make_middleware(
            available_tools=[t1],
            tool_registry={"from_registry": reg_tool},
        )
        collected = mw._collect_tools()
        names = [t.name for t in collected]
        assert "from_avail" in names
        assert "from_registry" in names

    def test_excludes_registry_tools_in_excluded(self):
        reg_tool = _make_tool("excluded_reg")
        mw = _make_middleware(
            tool_registry={"excluded_reg": reg_tool},
            excluded_tool_names={"excluded_reg"},
        )
        collected = mw._collect_tools()
        names = [t.name for t in collected]
        assert "excluded_reg" not in names


# ---------------------------------------------------------------------------
# _bind_tools_from_registry
# ---------------------------------------------------------------------------


class TestBindToolsFromRegistry:
    def test_binds_from_registry(self):
        reg_tool = _make_tool("tool_a")
        mw = _make_middleware(tool_registry={"tool_a": reg_tool})
        tools_by_name: dict[str, Any] = {}
        bound: set[str] = set()
        newly = mw._bind_tools_from_registry(["tool_a"], tools_by_name, bound)
        assert newly == ["tool_a"]
        assert "tool_a" in tools_by_name
        assert "tool_a" in bound

    def test_skips_already_bound(self):
        reg_tool = _make_tool("tool_a")
        mw = _make_middleware(tool_registry={"tool_a": reg_tool})
        tools_by_name: dict[str, Any] = {"tool_a": reg_tool}
        bound: set[str] = {"tool_a"}
        newly = mw._bind_tools_from_registry(["tool_a"], tools_by_name, bound)
        assert newly == []

    def test_skips_excluded(self):
        reg_tool = _make_tool("spawn_subagent")
        mw = _make_middleware(tool_registry={"spawn_subagent": reg_tool})
        tools_by_name: dict[str, Any] = {}
        bound: set[str] = set()
        newly = mw._bind_tools_from_registry(["spawn_subagent"], tools_by_name, bound)
        assert newly == []

    def test_no_registry_returns_empty(self):
        mw = _make_middleware(tool_registry=None)
        tools_by_name: dict[str, Any] = {}
        bound: set[str] = set()
        newly = mw._bind_tools_from_registry(["tool_a"], tools_by_name, bound)
        assert newly == []

    def test_skips_unknown_tools(self):
        mw = _make_middleware(tool_registry={"tool_a": _make_tool("tool_a")})
        tools_by_name: dict[str, Any] = {}
        bound: set[str] = set()
        newly = mw._bind_tools_from_registry(["unknown"], tools_by_name, bound)
        assert newly == []


# ---------------------------------------------------------------------------
# _build_retrieve_tool
# ---------------------------------------------------------------------------


class TestBuildRetrieveTool:
    def test_returns_none_when_no_store(self):
        mw = _make_middleware(store=None)
        result = mw._build_retrieve_tool(_make_config())
        assert result is None

    def test_returns_none_when_disabled(self):
        from app.agents.tools.core.tool_runtime_config import ToolRuntimeConfig

        config = ToolRuntimeConfig(enable_retrieve_tools=False)
        mw = _make_middleware(store=MagicMock(), tool_runtime_config=config)
        result = mw._build_retrieve_tool(_make_config())
        assert result is None

    def test_returns_structured_tool_when_configured(self):
        mw = _make_middleware(store=MagicMock())
        result = mw._build_retrieve_tool(_make_config())
        assert result is not None
        assert result.name == "retrieve_tools"


# ---------------------------------------------------------------------------
# _build_child_toolset
# ---------------------------------------------------------------------------


class TestBuildChildToolset:
    def test_dynamic_mode_with_store_and_registry(self):
        reg_tool = _make_tool("vfs_read")
        mw = _make_middleware(
            store=MagicMock(),
            tool_registry={"vfs_read": reg_tool, "vfs_cmd": _make_tool("vfs_cmd")},
        )
        tools_by_name, dynamic, retrieve_tool = mw._build_child_toolset(
            config=_make_config()
        )
        assert dynamic is True
        assert retrieve_tool is not None
        assert "retrieve_tools" in tools_by_name

    def test_inherits_parent_tools(self):
        reg_tool = _make_tool("parent_tool")
        mw = _make_middleware(
            store=MagicMock(),
            tool_registry={
                "parent_tool": reg_tool,
                "vfs_read": _make_tool("vfs_read"),
                "vfs_cmd": _make_tool("vfs_cmd"),
            },
        )
        tools_by_name, _, _ = mw._build_child_toolset(
            config=_make_config(),
            inherited_tool_names=["parent_tool"],
        )
        assert "parent_tool" in tools_by_name

    def test_fallback_when_empty(self):
        t1 = _make_tool("fallback_tool")
        from app.agents.tools.core.tool_runtime_config import ToolRuntimeConfig

        config = ToolRuntimeConfig(
            initial_tool_names=[],
            enable_retrieve_tools=False,
        )
        mw = _make_middleware(
            available_tools=[t1],
            tool_runtime_config=config,
            store=None,
            tool_registry=None,
        )
        tools_by_name, dynamic, retrieve_tool = mw._build_child_toolset(
            config=_make_config()
        )
        assert dynamic is False
        assert retrieve_tool is None
        assert "fallback_tool" in tools_by_name


# ---------------------------------------------------------------------------
# _execute_subagent
# ---------------------------------------------------------------------------


class TestExecuteSubagent:
    @pytest.mark.asyncio
    async def test_raises_when_no_llm(self):
        mw = _make_middleware(llm=None)
        with pytest.raises(ValueError, match="LLM not configured"):
            await mw._execute_subagent("task", "", _make_config())

    @pytest.mark.asyncio
    async def test_simple_text_response(self):
        """LLM returns text without tool calls."""
        mock_llm = MagicMock()
        response = AIMessage(content="Done!")
        response.tool_calls = []
        mock_llm.with_config.return_value = mock_llm
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=response)

        mw = _make_middleware(llm=mock_llm)
        result = await mw._execute_subagent("do something", "", _make_config())
        assert result == "Done!"

    @pytest.mark.asyncio
    async def test_empty_content_returns_task_completed(self):
        mock_llm = MagicMock()
        response = AIMessage(content="")
        response.tool_calls = []
        mock_llm.with_config.return_value = mock_llm
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=response)

        mw = _make_middleware(llm=mock_llm)
        result = await mw._execute_subagent("task", "", _make_config())
        assert result == "Task completed."

    @pytest.mark.asyncio
    async def test_tool_call_flow(self):
        """LLM calls a tool, then returns final answer."""
        mock_llm = MagicMock()
        mock_llm.with_config.return_value = mock_llm

        tool_call_response = AIMessage(content="")
        tool_call_response.tool_calls = [
            {"name": "my_tool", "args": {"x": 1}, "id": "tc1"}
        ]

        final_response = AIMessage(content="All done.")
        final_response.tool_calls = []

        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(side_effect=[tool_call_response, final_response])

        my_tool = _make_tool("my_tool")
        mw = _make_middleware(
            llm=mock_llm,
            tool_registry={
                "my_tool": my_tool,
                "vfs_read": _make_tool("vfs_read"),
                "vfs_cmd": _make_tool("vfs_cmd"),
            },
            store=MagicMock(),
        )

        result = await mw._execute_subagent(
            "do task", "", _make_config(), inherited_tool_names=["my_tool"]
        )
        assert result == "All done."
        my_tool.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error_message(self):
        """LLM calls a tool that doesn't exist."""
        mock_llm = MagicMock()
        mock_llm.with_config.return_value = mock_llm

        tool_call_response = AIMessage(content="")
        tool_call_response.tool_calls = [
            {"name": "unknown_tool", "args": {}, "id": "tc1"}
        ]

        final_response = AIMessage(content="Sorry.")
        final_response.tool_calls = []

        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(side_effect=[tool_call_response, final_response])

        mw = _make_middleware(
            llm=mock_llm,
            tool_registry={
                "vfs_read": _make_tool("vfs_read"),
                "vfs_cmd": _make_tool("vfs_cmd"),
            },
            store=MagicMock(),
        )

        result = await mw._execute_subagent("task", "", _make_config())
        assert result == "Sorry."

    @pytest.mark.asyncio
    async def test_retrieve_tools_call_rebinds(self):
        """When LLM calls retrieve_tools, new tools get bound."""
        mock_llm = MagicMock()
        mock_llm.with_config.return_value = mock_llm

        retrieve_call = AIMessage(content="")
        retrieve_call.tool_calls = [
            {"name": "retrieve_tools", "args": {"query": "email"}, "id": "tc1"}
        ]

        final_response = AIMessage(content="Found tools.")
        final_response.tool_calls = []

        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(side_effect=[retrieve_call, final_response])

        new_tool = _make_tool("new_tool")
        registry = {
            "vfs_read": _make_tool("vfs_read"),
            "vfs_cmd": _make_tool("vfs_cmd"),
            "new_tool": new_tool,
        }

        with patch(
            "app.agents.middleware.subagent.get_retrieve_tools_function",
            return_value=AsyncMock(
                return_value={"tools_to_bind": ["new_tool"], "response": ["new_tool"]}
            ),
        ):
            from app.agents.middleware.subagent import SubagentMiddleware

            mw = SubagentMiddleware(
                llm=mock_llm,
                tool_registry=registry,
                store=MagicMock(),
                max_turns=5,
            )

        result = await mw._execute_subagent("task", "", _make_config())
        assert result == "Found tools."
        # bind_tools called more than once (initial + after retrieve)
        assert mock_llm.bind_tools.call_count >= 2

    @pytest.mark.asyncio
    async def test_tool_invocation_error_returns_error_message(self):
        """Tool invocation that raises an exception."""
        mock_llm = MagicMock()
        mock_llm.with_config.return_value = mock_llm

        tool_call_response = AIMessage(content="")
        tool_call_response.tool_calls = [{"name": "fail_tool", "args": {}, "id": "tc1"}]

        final_response = AIMessage(content="Recovered.")
        final_response.tool_calls = []

        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(side_effect=[tool_call_response, final_response])

        fail_tool = _make_tool("fail_tool")
        fail_tool.ainvoke = AsyncMock(side_effect=RuntimeError("tool broke"))

        mw = _make_middleware(
            llm=mock_llm,
            tool_registry={
                "fail_tool": fail_tool,
                "vfs_read": _make_tool("vfs_read"),
                "vfs_cmd": _make_tool("vfs_cmd"),
            },
            store=MagicMock(),
        )

        result = await mw._execute_subagent("task", "", _make_config())
        assert result == "Recovered."

    @pytest.mark.asyncio
    async def test_max_turns_reached(self):
        """Subagent exhausts max turns and gets final response."""
        mock_llm = MagicMock()
        mock_llm.with_config.return_value = mock_llm

        # Every response has a tool call, never stops
        tool_call_response = AIMessage(content="")
        tool_call_response.tool_calls = [{"name": "vfs_read", "args": {}, "id": "tc1"}]

        final_msg = AIMessage(content="Max turns hit.")

        vfs_read = _make_tool("vfs_read")
        vfs_cmd = _make_tool("vfs_cmd")

        # max_turns=2: 2 tool-calling iterations + 1 final
        call_count = [0]

        async def mock_ainvoke(messages, config=None):
            call_count[0] += 1
            if call_count[0] <= 2:
                resp = AIMessage(content="")
                resp.tool_calls = [
                    {"name": "vfs_read", "args": {}, "id": f"tc{call_count[0]}"}
                ]
                return resp
            return final_msg

        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(side_effect=mock_ainvoke)

        from app.agents.tools.core.tool_runtime_config import ToolRuntimeConfig

        mw = _make_middleware(
            llm=mock_llm,
            tool_registry={"vfs_read": vfs_read, "vfs_cmd": vfs_cmd},
            store=MagicMock(),
            max_turns=2,
            tool_runtime_config=ToolRuntimeConfig(
                initial_tool_names=["vfs_read", "vfs_cmd"],
                enable_retrieve_tools=False,
            ),
        )

        result = await mw._execute_subagent("task", "", _make_config())
        assert result == "Max turns hit."

    @pytest.mark.asyncio
    async def test_context_included_in_messages(self):
        """Context string is prepended to the user message."""
        mock_llm = MagicMock()
        mock_llm.with_config.return_value = mock_llm

        response = AIMessage(content="ok")
        response.tool_calls = []
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=response)

        mw = _make_middleware(llm=mock_llm)
        await mw._execute_subagent("task", "my context", _make_config())

        call_args = mock_llm.ainvoke.call_args[0][0]
        user_msg = [m for m in call_args if isinstance(m, HumanMessage)][0]
        assert "my context" in user_msg.content
        assert "task" in user_msg.content

    @pytest.mark.asyncio
    async def test_retrieve_tools_error_handled(self):
        """retrieve_tools call that raises is caught gracefully."""
        mock_llm = MagicMock()
        mock_llm.with_config.return_value = mock_llm

        retrieve_call = AIMessage(content="")
        retrieve_call.tool_calls = [
            {"name": "retrieve_tools", "args": {"query": "x"}, "id": "tc1"}
        ]

        final_response = AIMessage(content="Handled error.")
        final_response.tool_calls = []

        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(side_effect=[retrieve_call, final_response])

        failing_retrieve = AsyncMock(side_effect=RuntimeError("retrieve fail"))

        with patch(
            "app.agents.middleware.subagent.get_retrieve_tools_function",
            return_value=failing_retrieve,
        ):
            from app.agents.middleware.subagent import SubagentMiddleware

            mw = SubagentMiddleware(
                llm=mock_llm,
                tool_registry={
                    "vfs_read": _make_tool("vfs_read"),
                    "vfs_cmd": _make_tool("vfs_cmd"),
                },
                store=MagicMock(),
                max_turns=5,
            )

        result = await mw._execute_subagent("task", "", _make_config())
        assert result == "Handled error."


# ---------------------------------------------------------------------------
# spawn_subagent tool (integration-style)
# ---------------------------------------------------------------------------


class TestSpawnSubagentTool:
    def test_tool_created(self):
        mw = _make_middleware()
        assert len(mw.tools) == 1
        tool = mw.tools[0]
        assert tool.name == "spawn_subagent"
