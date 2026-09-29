"""Render a tool's contract as a compact text doc for the model.

This is what replaces bind_tools for proxied tools: the model reads this doc
and constructs `data` for execute() from it. The args carry what building a
call needs; the return shape is keys and types only. get_tool_schema always
renders it; discovery docs render args only unless ENABLE_INLINE_TOOL_RETURNS is on.
"""

from app.agents.tools.execute.schema_notation import (
    render_args_budgeted,
    render_compact_type_budgeted,
)
from app.agents.tools.execute.tool_info import ToolContract
from app.constants.execute import ARGS_SCHEMA_MAX_CHARS, EXECUTE_TOOL_NAME
from app.utils.general_utils import clip_text

_DESCRIPTION_MAX_CHARS = 600
_UNDOCUMENTED_RETURNS = (
    "Return shape: not documented yet; it is learned from real calls. "
    "Inspect the first response before consuming fields."
)


def render_tool_doc(info: ToolContract, returns_budget: int | None) -> str:
    """One tool's doc: description, args, and its return shape within returns_budget; None renders args only."""
    lines = [f"## {info.tool_name}"]
    if info.description:
        lines.append(clip_text(info.description, _DESCRIPTION_MAX_CHARS))
    lines.append(f"Args for {EXECUTE_TOOL_NAME}(tool_name=..., data={{...}}), ? = optional:")
    lines.append(render_args_budgeted(info.input_schema, ARGS_SCHEMA_MAX_CHARS))
    if returns_budget is not None:
        lines.extend(_returns_lines(info, returns_budget))
    lines.append(
        f'Run it with: {EXECUTE_TOOL_NAME}(task_description="...", '
        f'tool_name="{info.tool_name}", data={{...}})'
    )
    return "\n".join(lines)


def _returns_lines(info: ToolContract, budget: int) -> list[str]:
    returns = info.effective_output_schema
    if returns is None:
        return [_UNDOCUMENTED_RETURNS]
    lines = [f"Returns: {render_compact_type_budgeted(returns, budget)}"]
    if info.provider_output_schema is None:
        lines.append(f"(shape observed from {info.observed_call_count} real calls)")
    return lines
