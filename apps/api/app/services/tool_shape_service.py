"""Learn tool output shapes from real dispatch results.

Every proxied tool response funnels through ``dispatch_tool``, so the observed
shape converges on ground truth with use — including for MCP and Composio tools
whose providers document no output schema at all. Only structure is learned:
keys, types, array-ness. Values never leave this module; arrays are sampled.

The one classification that matters is record vs map. A record's keys ARE its
schema; a map's keys are data, and modeling them as properties is a wrong
schema — worse at the shared scopes, where one user's data keys would merge
into the record every other user reads. A dict is read as a map when it is wide
(more keys than a record plausibly has) or when a key is not identifier-shaped
(spaces, punctuation, non-ASCII, an id/UUID). Map values are sampled and stored
as ``additionalProperties`` — the keys themselves are never stored.

What is NOT a map signal is value homogeneity: ``{sender, recipient}`` and
``{billing_address, shipping_address}`` are records whose fields share a shape,
and collapsing them would discard real field names permanently. So a small dict
of identifier-shaped keys is read as a record even when its values repeat —
the irreducible ambiguity resolved toward the reading that never destroys a
genuine record.

Records are scoped (``ResolvedTool.shape_scope``): "global" for catalog tools,
per-integration for MCP, so a private server's shapes stay with its users.

Concurrent read-merge-write can drop one observation to a race; the schema
converges over subsequent calls, so no lock is warranted.
"""

import json
import re
from typing import cast

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
# replaced passed everything it had not thought of. Provider field names are
# identifier-shaped (snake/camel/kebab/dotted); user-authored labels carry
# spaces, punctuation or non-ASCII and are not.
_FIELD_NAME_KEY = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$.\-]{0,63}$")
# Identifier-shaped but still data: message/phone ids, hex UUIDs.
_ID_LIKE_KEY = re.compile(r"\d{6,}|^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}|^[0-9a-fA-F]{32}$")

# How a map rides through genson, which only speaks ``properties``: its sampled
# values become an array under this one key so genson unions their shapes
# (optional fields and mixed types included), and the stored/rendered form
# rewrites that to ``additionalProperties``. Collision-free by construction —
# ``*`` fails the field-name allowlist, so no observed key can become it.
_MAP_KEY_SENTINEL = "*"


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
        builder.add_schema(_additional_to_sentinel(existing.output_schema))
    builder.add_object(_sample(output))
    schema = builder.to_schema()
    schema.pop("$schema", None)
    schema = cast(dict[str, object], _sentinel_to_additional(schema))
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
        return _sample_dict(node)
    if node is None or isinstance(node, str | int | float | bool):
        return node
    # Non-JSON scalar (datetime, Decimal, ...): its serialized form is a string.
    return str(node)


def _sample_dict(node: dict[object, object]) -> dict[str, object]:
    keys = [str(key) for key in node]
    if len(keys) > TOOL_SHAPE_MAX_KEYS_PER_OBJECT or not all(_is_field_name(key) for key in keys):
        # A map keyed by data. Its values ride as a sampled list so genson
        # unions their shapes — an optional field or a differing type in a
        # later entry survives, not just whatever the first entry carried.
        values = list(node.values())[:TOOL_SHAPE_ARRAY_SAMPLE]
        return {_MAP_KEY_SENTINEL: [_sample(value) for value in values]}
    return {str(key): _sample(value) for key, value in node.items()}


def _sentinel_to_additional(node: object) -> object:
    """The stored/rendered form: the sentinel property becomes ``additionalProperties``.

    The sentinel is encoded as an array of sampled values (see ``_sample_dict``),
    so its ``items`` schema is the map's value shape. Named properties learned
    from other observations of the same node survive beside it — valid JSON
    Schema, and the honest reading of mixed evidence.
    """
    if isinstance(node, list):
        return [_sentinel_to_additional(item) for item in node]
    if not isinstance(node, dict):
        return node
    out = {key: _sentinel_to_additional(value) for key, value in node.items()}
    properties = out.get("properties")
    if isinstance(properties, dict) and _MAP_KEY_SENTINEL in properties:
        sentinel = properties.pop(_MAP_KEY_SENTINEL)
        out["additionalProperties"] = (
            sentinel.get("items", {}) if isinstance(sentinel, dict) else {}
        )
        if not properties:
            del out["properties"]
        required = out.get("required")
        if isinstance(required, list):
            out["required"] = [name for name in required if name != _MAP_KEY_SENTINEL]
            if not out["required"]:
                del out["required"]
    return out


def _additional_to_sentinel(node: object) -> object:
    """The inverse rewrite, so a stored schema re-enters genson's dialect as the
    array-of-values the sentinel encodes."""
    if isinstance(node, list):
        return [_additional_to_sentinel(item) for item in node]
    if not isinstance(node, dict):
        return node
    out = {key: _additional_to_sentinel(value) for key, value in node.items()}
    additional = out.get("additionalProperties")
    if isinstance(additional, dict):
        del out["additionalProperties"]
        properties = out.setdefault("properties", {})
        if isinstance(properties, dict):
            properties[_MAP_KEY_SENTINEL] = {"type": "array", "items": additional}
    return out
