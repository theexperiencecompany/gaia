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
from pymongo.errors import PyMongoError

from app.agents.tools.execute.resolver import ResolvedTool, resolve_tool
from app.agents.tools.execute.schema_notation import render_compact_type
from app.constants.execute import RESPONSE_SCHEMA_METADATA_KEYS
from app.constants.log_tags import LogTag
from app.db.repositories.tool_shapes import tool_shapes_repository
from app.models.json_schema_models import JsonSchemaNode
from app.models.tool_shape_models import ToolOutputShapeDocument
from shared.py.wide_events import log

# Composio's wrapper injects a config-passthrough parameter into the synthesized
# signature; it is plumbing, never something the model supplies.
_INTERNAL_ARG_NAMES = {"__runnable_config__"}
_TITLE = "title"
_REQUIRED = "required"
# Keywords whose value maps names to schemas: a key there is a field, never an annotation.
_SCHEMA_MAPS = frozenset({"properties", "patternProperties", "$defs", "definitions"})


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
    def effective_output_schema(self) -> dict[str, JsonValue] | None:
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
    return contract_from(resolved, await _observed_shape(resolved))


def contract_from(resolved: ResolvedTool, observed: ToolOutputShapeDocument | None) -> ToolContract:
    """Build a resolved tool's contract around an observed shape, or none, without touching the store."""
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


async def _observed_shape(resolved: ResolvedTool) -> ToolOutputShapeDocument | None:
    """The shape learned from real calls, or None when the store is unreachable: it only enriches the doc."""
    try:
        return await tool_shapes_repository.get_shape(resolved.shape_scope, resolved.name)
    except PyMongoError as e:
        log.warning(
            f"{LogTag.TOOL} tool contract: observed shape unavailable",
            tool_name=resolved.name,
            error_type=type(e).__name__,
        )
        return None


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
    node: JsonSchemaNode = cast(JsonSchemaNode, compacted)
    properties = node.get("properties")
    if isinstance(properties, dict):
        for name in _INTERNAL_ARG_NAMES:
            properties.pop(name, None)
        if isinstance(node.get("required"), list):
            node["required"] = [r for r in node["required"] if r not in _INTERNAL_ARG_NAMES]
    return compacted


def _strip_noise(node: JsonValue, *, keys_are_names: bool = False) -> JsonValue:
    """Drop the title annotation and keep only string names in required.

    A key of a name-to-schema map is a field name, so a field called title or
    required is kept as it is.
    """
    if isinstance(node, dict):
        return {
            key: (
                _required_names(value)
                if not keys_are_names and key == _REQUIRED
                else _strip_noise(value, keys_are_names=not keys_are_names and key in _SCHEMA_MAPS)
            )
            for key, value in node.items()
            if keys_are_names or key != _TITLE
        }
    if isinstance(node, list):
        return [_strip_noise(item) for item in node]
    return node


def _required_names(value: JsonValue) -> JsonValue:
    """A provider's required list as field names only; anything else there names no field."""
    if not isinstance(value, list):
        return []
    return [name for name in value if isinstance(name, str)]
