"""Learn tool output shapes from real dispatch results.

Every proxied tool response funnels through ``dispatch_tool``, so the observed
shape converges on ground truth with use — including for MCP and Composio tools
whose providers document no output schema at all. Only structure is learned:
keys, types, array-ness. Arrays are sampled, wide dicts are treated as maps,
dicts with value-looking keys (emails, ids, UUIDs) collapse to maps so data can
never become schema property names, and values themselves never leave this
function.

Records are scoped (``ResolvedTool.shape_scope``): "global" for catalog tools,
per-integration for MCP, so a private server's shapes stay with its users.

Concurrent read-merge-write can drop one observation to a race; the schema
converges over subsequent calls, so no lock is warranted.
"""

import json
import re

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

# A key that looks like data rather than a field name: email-ish, a long digit
# run (phone/message ids), UUID-shaped, or implausibly long for an identifier.
_VALUE_LIKE_KEY = re.compile(r"@|\d{6,}|^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-|.{65,}", re.DOTALL)


async def record_observed_shape(tool_name: str, output: object, *, scope: str) -> None:
    """Merge one real output's structure into the tool's stored shape."""
    if not isinstance(output, dict):
        # Plain-string/None outputs teach nothing a script needs.
        return
    builder = SchemaBuilder()
    existing = await tool_shapes_repository.get_shape(scope, tool_name)
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
    await tool_shapes_repository.record(scope, tool_name, schema)


async def observed_shapes_for(
    scoped_names: list[tuple[str, str]],
) -> dict[str, ToolOutputShapeDocument]:
    """Shapes for exact ``(scope, tool_name)`` pairs, keyed by tool name."""
    docs = await tool_shapes_repository.get_many(scoped_names)
    return {doc.tool_name: doc for doc in docs}


def _sample(node: object) -> object:
    """A structure-preserving skeleton of ``node`` for schema inference."""
    if isinstance(node, list):
        return [_sample(item) for item in node[:TOOL_SHAPE_ARRAY_SAMPLE]]
    if isinstance(node, dict):
        keys = [str(key) for key in node]
        if len(keys) > TOOL_SHAPE_MAX_KEYS_PER_OBJECT or any(
            _VALUE_LIKE_KEY.search(key) for key in keys
        ):
            # A map keyed by data, not a record with field names.
            return {}
        return {str(key): _sample(value) for key, value in node.items()}
    if node is None or isinstance(node, str | int | float | bool):
        return node
    # Non-JSON scalar (datetime, Decimal, ...): its serialized form is a string.
    return str(node)
