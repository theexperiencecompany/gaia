"""The LLM-facing execute proxy tool."""

from collections.abc import Mapping
import json
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from app.agents.tools.execute.dispatch import dispatch_tool
from app.models.agent_models import agent_configurable


def build_execute_tool(scoped_tools: Mapping[str, BaseTool] | None = None) -> BaseTool:
    """The execute proxy, optionally confined to one agent's tool space.

    ``scoped_tools`` is a subagent's live tool dict — read at call time, so it
    reflects the whole dict however late a tool was added to it. Pass it and a
    registered tool outside that dict is refused, exactly as ``retrieve_tools``
    refuses to bind one; the executor passes nothing, because its space is the
    registry. Without this the proxy resolved every name globally and a Gmail
    subagent could run Slack's tools, leaving the retrieve_tools guard
    decorative for every integration tool.
    """

    @tool
    async def execute(
        config: RunnableConfig,
        task_description: Annotated[
            str,
            "One short user-facing line describing what this call does, e.g. "
            "'Archiving 3 promotional emails'. Shown on the tool card in the UI.",
        ],
        tool_name: Annotated[
            str,
            "Exact tool name to run, verbatim from retrieve_tools (e.g. 'GMAIL_SEND_EMAIL').",
        ],
        data: Annotated[
            dict[str, Any],
            "Arguments for tool_name, matching the args schema retrieve_tools showed. "
            "Pass {} when the tool takes no arguments.",
        ],
    ) -> str:
        """Run an integration tool (Gmail, GitHub, Notion, MCP, ...) by name.

        Integration tools are not called directly: discover them and read their
        args schema with retrieve_tools, then run them through execute. On an
        unknown_tool or invalid_args error, correct tool_name/data per the error
        detail and retry once. Never retry the identical call.
        """
        # UI-facing arg: consumed by the stream formatter (card label), not here.
        del task_description
        result = await dispatch_tool(
            user_id=agent_configurable(config).get("user_id"),
            tool_name=tool_name,
            data=data,
            config=config,
            scoped_tool_names=None if scoped_tools is None else set(scoped_tools),
        )
        if not result.ok and result.error is not None:
            return json.dumps(
                {
                    "ok": False,
                    "error": result.error.kind,
                    "detail": result.error.detail,
                    "next": result.error.hint,
                }
            )
        output = result.output
        return output if isinstance(output, str) else json.dumps(output, default=str)

    return execute


# The unscoped proxy the global registry publishes — the executor's space is the
# whole registry, so it needs no confinement.
execute = build_execute_tool()
