"""A tool's full contract: args, provider return shape and the shape observed from real calls.

Three surfaces render this one assembler: the retrieve_tools discovery docs,
the host-side ``get_tool_schema`` tool, and the sandbox route (``gaia.schema`` /
the tool-docs file). Unbudgeted JSON lives here for the file; anything that
enters model context uses the compact notation instead — a raw provider schema
can run to hundreds of thousands of characters (GOOGLEDOCS_GET_DOCUMENT_BY_ID: 306K).
"""

from typing import Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, JsonValue

from app.agents.tools.execute.resolver import ResolvedTool, resolve_tool
from app.agents.tools.execute.schema_notation import _SchemaNode, render_compact_type
from app.constants.execute import RESPONSE_SCHEMA_METADATA_KEYS
from app.db.repositories.tool_shapes import tool_shapes_repository

# Composio's wrapper injects a config-passthrough parameter into the synthesized
# signature; it is plumbing, never something the model supplies.
_INTERNAL_ARG_NAMES = {"__runnable_config__"}


class ToolContract(BaseModel):
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

    @property
    def effective_output_schema(self) -> dict[str, Any] | None:
        """The provider's return shape, else the one observed from real calls."""
        return self.provider_output_schema or self.observed_output_schema


async def full_tool_info(user_id: str | None, tool_name: str) -> ToolContract | None:
    """The complete contract for one tool, or ``None`` if the name is unknown."""
    resolved = await resolve_tool(user_id, tool_name)
    if resolved is None:
        return None
    return await tool_contract(resolved)


async def tool_contract(resolved: ResolvedTool) -> ToolContract:
    """The contract of an already-resolved tool, with its observed shape read from the store."""
    observed = await tool_shapes_repository.get_shape(resolved.shape_scope, resolved.name)
    contract = ToolContract(
        tool_name=resolved.name,
        description=resolved.tool.description.strip(),
        input_schema=_args_schema_of(resolved.tool),
        provider_output_schema=_response_schema_of(resolved.tool),
        observed_output_schema=observed.output_schema if observed is not None else None,
        observed_call_count=observed.call_count if observed is not None else 0,
    )
    effective = contract.effective_output_schema
    contract.compact_output_type = render_compact_type(effective) if effective else None
    return contract


def _args_schema_of(tool: BaseTool) -> dict[str, JsonValue]:
    schema = tool.args_schema
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        raw = schema.model_json_schema()
    elif isinstance(schema, dict):
        raw = dict(schema)
    else:
        raw = {"type": "object", "properties": {}}
    return _compact_schema(raw)


def _response_schema_of(tool: BaseTool) -> dict[str, JsonValue] | None:
    metadata = tool.metadata or {}
    for key in RESPONSE_SCHEMA_METADATA_KEYS:
        value = metadata.get(key)
        if isinstance(value, dict) and value:
            return _compact_schema(value)
    return None


def _compact_schema(schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Strip generator noise (titles, internal params, $defs plumbing keys)."""
    # cast, not isinstance: _strip_noise maps dict->dict by construction.
    compacted = cast(dict[str, JsonValue], _strip_noise(schema))
    node: _SchemaNode = cast(_SchemaNode, compacted)
    properties = node.get("properties")
    if isinstance(properties, dict):
        for name in _INTERNAL_ARG_NAMES:
            properties.pop(name, None)
        if isinstance(node.get("required"), list):
            node["required"] = [r for r in node["required"] if r not in _INTERNAL_ARG_NAMES]
    return compacted


def _strip_noise(node: JsonValue) -> JsonValue:
    if isinstance(node, dict):
        return {key: _strip_noise(value) for key, value in node.items() if key not in {"title"}}
    if isinstance(node, list):
        return [_strip_noise(item) for item in node]
    return node
