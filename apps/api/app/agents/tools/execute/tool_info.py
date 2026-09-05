"""Full tool documentation for on-demand lookup, behind the discovery pointer.

Two transports share this assembler: the host-side ``get_tool_schema`` tool and
the sandbox route (``gaia.schema`` / the tool-docs file). Unbudgeted JSON lives
here for the file; anything that enters model context uses the compact type
notation instead — a raw provider schema can run to hundreds of thousands of
characters (GOOGLEDOCS_GET_DOCUMENT_BY_ID: 306K).
"""

from typing import Any

from pydantic import BaseModel

from app.agents.tools.execute.resolver import resolve_tool
from app.agents.tools.execute.schema_docs import (
    _args_schema_of,
    _response_schema_of,
    render_compact_type,
)
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
    # The effective return shape (provider, else observed) as terse type
    # notation — the form every context-bound surface renders.
    compact_output_type: str | None = None


async def full_tool_info(user_id: str | None, tool_name: str) -> ToolInfo | None:
    """The complete contract for one tool, or ``None`` if the name is unknown."""
    resolved = await resolve_tool(user_id, tool_name)
    if resolved is None:
        return None
    observed = await tool_shapes_repository.get_shape(resolved.shape_scope, resolved.name)
    provider_schema = _response_schema_of(resolved.tool)
    effective = provider_schema or (observed.output_schema if observed is not None else None)
    return ToolInfo(
        tool_name=resolved.name,
        description=(resolved.tool.description or "").strip(),
        input_schema=_args_schema_of(resolved.tool),
        provider_output_schema=provider_schema,
        observed_output_schema=observed.output_schema if observed is not None else None,
        observed_call_count=observed.call_count if observed is not None else 0,
        compact_output_type=render_compact_type(effective) if effective else None,
    )
