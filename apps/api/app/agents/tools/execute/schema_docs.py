"""Render a tool's contract as a compact text doc for the model.

This is what replaces bind_tools for proxied tools: the model reads this doc
and constructs `data` for execute() from it. Docs carry args only, budgeted
and depth-pruned when oversized (never clipped mid-JSON). Return shapes are
deliberately NOT in discovery docs: they are explored on demand through
get_tool_schema (host) or gaia.schema/the tool-docs files (sandbox), so the
context pays for a shape only when something actually consumes it.
"""

import json
from typing import cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, JsonValue

from app.constants.execute import (
    ARGS_SCHEMA_MAX_CHARS,
    EXECUTE_TOOL_NAME,
    RESPONSE_SCHEMA_METADATA_KEYS,
    SCHEMA_DOC_MAX_CHARS,
)
from app.models.json_schema_models import JsonSchemaNode
from app.utils.general_utils import clip_text

# Composio's wrapper injects a config-passthrough parameter into the synthesized
# signature; it is plumbing, never something the model supplies.
_INTERNAL_ARG_NAMES = {"__runnable_config__"}
_DESCRIPTION_MAX_CHARS = 600


def render_tool_doc(tool: BaseTool) -> str:
    """One tool's usage doc: description and args schema. Never the returns."""
    lines = [f"## {tool.name}"]
    description = tool.description.strip()
    if description:
        lines.append(clip_text(description, _DESCRIPTION_MAX_CHARS))
    lines.append("Args schema for execute(tool_name=..., data={...}):")
    lines.append(_render_budgeted_schema(_args_schema_of(tool), ARGS_SCHEMA_MAX_CHARS))
    lines.append(
        f'Run it with: {EXECUTE_TOOL_NAME}(task_description="...", '
        f'tool_name="{tool.name}", data={{...}})'
    )
    return clip_text("\n".join(lines), SCHEMA_DOC_MAX_CHARS)


def render_compact_type_budgeted(schema: dict[str, JsonValue], budget: int) -> str:
    """Compact type notation within budget, depth-collapsing when oversized."""
    rendered = render_compact_type(schema)
    if len(rendered) <= budget:
        return rendered
    for levels in _SCHEMA_PRUNE_LEVELS:
        # Pruned properties render as bare `obj`, so depth degrades gracefully.
        pruned = render_compact_type(cast(dict[str, JsonValue], _prune_to_levels(schema, levels)))
        if len(pruned) <= budget:
            return f"{pruned}\n(deeper fields omitted for size; the real data has them)"
    return clip_text(rendered, budget)


def render_compact_type(node: dict[str, JsonValue]) -> str:
    """A JSON schema as terse type notation, e.g. ``{id:str, tags?:str[]}``.

    Structure only — descriptions and schema ceremony are what make real
    provider schemas thousands of tokens; the fields and types are not.
    """
    return _compact_type(node)


def _compact_type(node: object) -> str:
    if not isinstance(node, dict):
        return "any"
    schema: JsonSchemaNode = cast(JsonSchemaNode, node)
    union = _compact_union(schema)
    if union is not None:
        return union
    obj = _compact_object(schema)
    if obj is not None:
        return obj
    arr = _compact_array(schema)
    if arr is not None:
        return arr
    enum = _compact_enum(schema)
    if enum is not None:
        return enum
    type_ = schema.get("type")
    return _COMPACT_PRIMITIVES.get(str(type_), str(type_) if type_ else "any")


def _compact_union(node: JsonSchemaNode) -> str | None:
    """A union schema (anyOf/oneOf/type-list) as ``a|b``, else None."""
    variants = node.get("anyOf") or node.get("oneOf")
    if isinstance(variants, list) and variants:
        return "|".join(sorted({_compact_type(variant) for variant in variants}))
    type_ = node.get("type")
    if isinstance(type_, list):
        return "|".join(sorted({_compact_type({**node, "type": t}) for t in type_}))
    return None


def _compact_object(node: JsonSchemaNode) -> str | None:
    """An object schema as ``{name:type, opt?:type, [key]:type}``, else None."""
    type_ = node.get("type")
    if type_ != "object" and not (type_ is None and "properties" in node):
        return None
    properties = node.get("properties")
    required = set(node.get("required") or [])
    fields = [
        f"{name}{'' if name in required else '?'}:{_compact_type(sub)}"
        for name, sub in (properties.items() if isinstance(properties, dict) else ())
    ]
    # A data-keyed map (observed shapes store these as additionalProperties):
    # rendered as an index signature, since the keys are data, not fields.
    additional = node.get("additionalProperties")
    if isinstance(additional, dict):
        fields.append(f"[key]:{_compact_type(additional)}")
    if not fields:
        return "obj"
    return "{" + ", ".join(fields) + "}"


def _compact_array(node: JsonSchemaNode) -> str | None:
    """An array schema as ``item[]`` (grouped when the item is a union), else None."""
    if node.get("type") != "array":
        return None
    item = _compact_type(node.get("items"))
    # Union item types need grouping so {a}|{b}[] cannot misread.
    return (f"({item})" if "|" in item else item) + "[]"


def _compact_enum(node: JsonSchemaNode) -> str | None:
    """A small closed enum as its JSON members joined by ``|``, else None."""
    enum = node.get("enum")
    if isinstance(enum, list) and 0 < len(enum) <= _COMPACT_ENUM_MAX_MEMBERS:
        return "|".join(json.dumps(value, default=str) for value in enum)
    return None


_COMPACT_PRIMITIVES = {
    "string": "str",
    "integer": "int",
    "number": "num",
    "boolean": "bool",
    "null": "null",
}
_COMPACT_ENUM_MAX_MEMBERS = 6


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


_SCHEMA_TRUNCATED_MARKER = "..."
_SCHEMA_TRUNCATION_NOTE = (
    '(schema truncated for size: "..." marks omitted nested fields; the real data has them)'
)
# Progressively shallower renders tried when the full schema exceeds its budget.
_SCHEMA_PRUNE_LEVELS = (3, 2, 1)


def _render_budgeted_schema(schema: dict[str, JsonValue], budget: int) -> str:
    """One schema section within budget: full, depth-pruned, or names-only."""
    full = _dumps(schema)
    if len(full) <= budget:
        return full
    for levels in _SCHEMA_PRUNE_LEVELS:
        pruned = _dumps(_prune_to_levels(schema, levels))
        if len(pruned) <= budget:
            return f"{pruned}\n{_SCHEMA_TRUNCATION_NOTE}"
    node: JsonSchemaNode = cast(JsonSchemaNode, schema)
    properties = node.get("properties")
    names = sorted(properties) if isinstance(properties, dict) else []
    floor = _dumps({"type": node.get("type", "object"), "fields": names})
    return f"{clip_text(floor, budget)}\n{_SCHEMA_TRUNCATION_NOTE}"


def _prune_to_levels(node: object, levels: int) -> object:
    """Depth-limit a JSON schema: nesting past `levels` collapses to a marker."""
    if isinstance(node, list):
        return [_prune_to_levels(item, levels) for item in node]
    if not isinstance(node, dict):
        return node
    pruned: dict[str, object] = {}
    for key, value in node.items():
        if key == "properties" and isinstance(value, dict):
            pruned[key] = (
                {name: _prune_to_levels(sub, levels - 1) for name, sub in value.items()}
                if levels > 0
                else _SCHEMA_TRUNCATED_MARKER
            )
        elif key in {"items", "additionalProperties"} and isinstance(value, dict | list):
            pruned[key] = (
                _prune_to_levels(value, levels - 1) if levels > 0 else _SCHEMA_TRUNCATED_MARKER
            )
        else:
            pruned[key] = _prune_to_levels(value, levels)
    return pruned


def _dumps(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


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


def _strip_noise(node: JsonValue) -> JsonValue:
    if isinstance(node, dict):
        return {key: _strip_noise(value) for key, value in node.items() if key not in {"title"}}
    if isinstance(node, list):
        return [_strip_noise(item) for item in node]
    return node
