"""The host-side depth lookup behind the discovery pointer.

The sandbox has gaia.schema()/the tool-docs file; a plain conversation has this
bound tool. Both sit on full_tool_info, so the two surfaces cannot drift. The
return shape renders as compact type notation, never raw schema JSON: a raw
provider schema can run to hundreds of thousands of characters.
"""

import json
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.tools.execute.schema_docs import (
    _render_budgeted_schema,
    render_compact_type_budgeted,
)
from app.agents.tools.execute.tool_info import full_tool_info
from app.constants.execute import ARGS_SCHEMA_MAX_CHARS, TOOL_SCHEMA_RETURNS_MAX_CHARS
from app.models.agent_models import agent_configurable
from app.utils.general_utils import clip_text

_DESCRIPTION_MAX_CHARS = 600


@tool
async def get_tool_schema(
    config: RunnableConfig,
    tool_name: Annotated[
        str,
        "Exact tool name, verbatim from retrieve_tools (e.g. 'GMAIL_FETCH_EMAILS').",
    ],
) -> str:
    """Full contract for one integration tool: args schema plus return shape.

    Use when a tool's doc points here instead of inlining its return shape,
    BEFORE writing code that consumes the tool's output; never guess shapes.
    Read-only metadata, runs nothing.
    """
    info = await full_tool_info(agent_configurable(config).get("user_id"), tool_name)
    if info is None:
        return json.dumps(
            {
                "ok": False,
                "error": "unknown_tool",
                "next": "Use the exact tool name retrieve_tools returned.",
            }
        )
    lines = [f"## {info.tool_name}"]
    if info.description:
        lines.append(clip_text(info.description, _DESCRIPTION_MAX_CHARS))
    lines.append("Args schema:")
    lines.append(_render_budgeted_schema(info.input_schema, ARGS_SCHEMA_MAX_CHARS))
    returns_schema = info.provider_output_schema or info.observed_output_schema
    if returns_schema is None:
        lines.append(
            "Return shape: not documented yet; it is learned from real calls. "
            "Inspect the first response before consuming fields."
        )
    else:
        lines.append(
            "Returns: "
            + render_compact_type_budgeted(returns_schema, TOOL_SCHEMA_RETURNS_MAX_CHARS)
        )
        if info.provider_output_schema is None:
            lines.append(f"(shape observed from {info.observed_call_count} real calls)")
    return "\n".join(lines)
