"""Learn tool output shapes from real dispatch results.

Every proxied tool response funnels through ``dispatch_tool``, so the observed
shape converges on ground truth with use — including for MCP and Composio tools
whose providers document no output schema at all. Only structure is learned:
keys, types, array-ness. Values never leave this function; arrays are sampled;
wide dicts and dicts whose keys are not identifier-shaped are treated as maps,
so a dict keyed by data ({"sarah@x.com": {...}}, {"Q3 spend / EMEA": {...}})
contributes its shape without contributing its keys.

Records are scoped (``ResolvedTool.shape_scope``): "global" for catalog tools,
per-integration for MCP, so a private server's shapes stay with its users. The
key test is a quality heuristic, NOT a privacy boundary: a user-authored label
that happens to be identifier-shaped (a spreadsheet tab, a one-word Notion
property) still reaches the shared record for a catalog tool.

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
from shared.py.wide_events import log

# What may become a schema property name: an ALLOWLIST, because the denylist it
# replaced passed everything it had not thought of — and a catalog tool's record
# is global, so one user's dict key is rendered back to every other user of that
# tool. Provider field names are identifier-shaped (snake/camel/kebab/dotted);
# user-authored labels carry spaces, punctuation or non-ASCII and are not.
_FIELD_NAME_KEY = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$.\-]{0,63}$")
# Identifier-shaped but still data: message/phone ids, hex UUIDs.
_ID_LIKE_KEY = re.compile(r"\d{6,}|^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}|^[0-9a-fA-F]{32}$")


def _is_field_name(key: str) -> bool:
    return bool(_FIELD_NAME_KEY.match(key)) and not _ID_LIKE_KEY.search(key)


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


def _sample(node: object) -> object:
    """A structure-preserving skeleton of ``node`` for schema inference."""
    if isinstance(node, list):
        return [_sample(item) for item in node[:TOOL_SHAPE_ARRAY_SAMPLE]]
    if isinstance(node, dict):
        keys = [str(key) for key in node]
        if len(keys) > TOOL_SHAPE_MAX_KEYS_PER_OBJECT or not all(
            _is_field_name(key) for key in keys
        ):
            # A map keyed by data, not a record with field names.
            return {}
        return {str(key): _sample(value) for key, value in node.items()}
    if node is None or isinstance(node, str | int | float | bool):
        return node
    # Non-JSON scalar (datetime, Decimal, ...): its serialized form is a string.
    return str(node)
