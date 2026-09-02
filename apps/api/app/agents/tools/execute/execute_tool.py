"""The LLM-facing execute proxy tool."""

import json
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.tools.execute.dispatch import dispatch_tool
from app.models.agent_models import agent_configurable


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

    Integration tools are not called directly: discover them and read their args
    schema with retrieve_tools, then run them through execute. On an
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
