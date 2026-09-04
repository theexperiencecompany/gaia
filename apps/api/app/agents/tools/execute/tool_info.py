"""Full tool documentation for on-demand lookup (gaia.schema in the sandbox).

Unbudgeted on purpose: the discovery doc inlines only small response shapes,
and this is the depth behind its pointer — fetched once, cached as a file in
the sandbox's tool-docs folder rather than re-paid as context every turn.
"""

from typing import Any

from pydantic import BaseModel

from app.agents.tools.execute.resolver import resolve_tool
from app.agents.tools.execute.schema_docs import _args_schema_of, _response_schema_of
from app.db.repositories.tool_shapes import tool_shapes_repository


class ToolInfo(BaseModel):
    """Everything known about one tool's contract, both provider and observed."""

    tool_name: str
    description: str
    input_schema: dict[str, Any]
    provider_output_schema: dict[str, Any] | None = None
    observed_output_schema: dict[str, Any] | None = None
    # Confidence signal: how many real responses the observed schema merges.
    observed_call_count: int = 0


async def full_tool_info(user_id: str | None, tool_name: str) -> ToolInfo | None:
    """The complete contract for one tool, or ``None`` if the name is unknown."""
    resolved = await resolve_tool(user_id, tool_name)
    if resolved is None:
        return None
    observed = await tool_shapes_repository.get_by_tool_name(resolved.name)
    return ToolInfo(
        tool_name=resolved.name,
        description=(resolved.tool.description or "").strip(),
        input_schema=_args_schema_of(resolved.tool),
        provider_output_schema=_response_schema_of(resolved.tool),
        observed_output_schema=observed.output_schema if observed is not None else None,
        observed_call_count=observed.call_count if observed is not None else 0,
    )
