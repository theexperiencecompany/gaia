"""Learn tool output shapes from real dispatch results.

Every proxied tool response funnels through ``dispatch_tool``, so the observed
shape converges on ground truth with use — including for MCP and Composio tools
whose providers document no output schema at all. Only structure is learned:
keys, types, array-ness. Arrays are sampled, wide dicts are treated as maps so
value-derived keys (emails, ids) never become schema property names, and values
themselves never leave this function.

Concurrent read-merge-write can drop one observation to a race; the schema
converges over subsequent calls, so no lock is warranted.
"""

import json

from genson import SchemaBuilder

from app.constants.execute import (
    TOOL_SHAPE_ARRAY_SAMPLE,
    TOOL_SHAPE_MAX_CHARS,
    TOOL_SHAPE_MAX_KEYS_PER_OBJECT,
)
from app.constants.log_tags import LogTag
from app.db.repositories.tool_shapes import tool_shapes_repository
from app.models.tool_shape_models import ToolOutputShapeDocument
from shared.py.wide_events import log


async def record_observed_shape(tool_name: str, output: object) -> None:
    """Merge one real output's structure into the tool's stored shape."""
    if not isinstance(output, dict):
        # Plain-string/None outputs teach nothing a script needs.
        return
    builder = SchemaBuilder()
    existing = await tool_shapes_repository.get_by_tool_name(tool_name)
    if existing is not None:
        builder.add_schema(existing.output_schema)
    builder.add_object(_sample(output))
    schema = builder.to_schema()
    schema.pop("$schema", None)
    if len(json.dumps(schema, default=str)) > TOOL_SHAPE_MAX_CHARS:
        log.warning(
            f"{LogTag.TOOL} observed shape exceeds the size cap; keeping the stored one",
            tool_name=tool_name,
        )
        return
    await tool_shapes_repository.record(tool_name, schema)


async def observed_shapes_for(tool_names: list[str]) -> dict[str, ToolOutputShapeDocument]:
    docs = await tool_shapes_repository.get_many(tool_names)
    return {doc.tool_name: doc for doc in docs}


def _sample(node: object) -> object:
    """A structure-preserving skeleton of ``node`` for schema inference."""
    if isinstance(node, list):
        return [_sample(item) for item in node[:TOOL_SHAPE_ARRAY_SAMPLE]]
    if isinstance(node, dict):
        if len(node) > TOOL_SHAPE_MAX_KEYS_PER_OBJECT:
            # A map keyed by data, not a record with field names.
            return {}
        return {str(key): _sample(value) for key, value in node.items()}
    if node is None or isinstance(node, str | int | float | bool):
        return node
    # Non-JSON scalar (datetime, Decimal, ...): its serialized form is a string.
    return str(node)
