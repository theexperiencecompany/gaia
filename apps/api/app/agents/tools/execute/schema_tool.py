"""The host-side depth lookup behind the discovery docs.

The sandbox has gaia.schema()/the tool-docs file; a plain conversation has this
bound tool. It renders the same doc retrieve_tools does, with a larger budget
for the return shape, so the two surfaces cannot drift.
"""

import json
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.tools.execute.schema_docs import render_tool_doc
from app.agents.tools.execute.tool_info import full_tool_info
from app.constants.execute import TOOL_SCHEMA_RETURNS_MAX_CHARS
from app.models.agent_models import AgentConfigurable, agent_configurable


@tool
async def get_tool_schema(
    config: RunnableConfig,
    tool_name: Annotated[
        str,
        "Exact tool name, verbatim from retrieve_tools (e.g. 'GMAIL_FETCH_EMAILS').",
    ],
) -> str:
    """Full contract for one integration tool: args plus the deepest return shape.

    Use when a retrieve_tools doc collapsed a large return shape and you need
    its deeper fields, BEFORE writing code that consumes them; never guess
    shapes. Read-only metadata, runs nothing.
    """
    configurable: AgentConfigurable = agent_configurable(config)
    info = await full_tool_info(configurable.get("user_id"), tool_name)
    if info is None:
        return json.dumps(
            {
                "ok": False,
                "error": "unknown_tool",
                "next": "Use the exact tool name retrieve_tools returned.",
            }
        )
    return render_tool_doc(info, TOOL_SCHEMA_RETURNS_MAX_CHARS)
