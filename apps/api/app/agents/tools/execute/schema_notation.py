"""JSON Schema as compact text for the model: type notation for returns, field lines for args.

Returns render as ``{id:str, tags?:str[]}``: structure only, the key and its type.
Args keep what constructing a call needs, one field per line with its
description and constraints; an oversized schema sheds description text before
it sheds any structure. Examples are never rendered: they are the bulk of real
provider schemas and repeat what the description already says.
"""

import json
from typing import TypedDict, cast

from pydantic import JsonValue

from app.utils.general_utils import clip_text


class _SchemaNode(TypedDict, total=False):
    """The JSON Schema keywords the renderers read off one schema node.

    Provider and observed schemas are never validated, so a keyword whose value
    varies by provider stays JsonValue and every read keeps its isinstance guard.
    """

    type: str | list[str]
    properties: dict[str, JsonValue]
    required: list[str]
    items: JsonValue
    anyOf: JsonValue
    oneOf: JsonValue
    enum: JsonValue
    const: JsonValue
    description: JsonValue
    additionalProperties: JsonValue


# Returns: a larger enum renders as its base type. Args list more members,
# since a value outside the set fails validation.
_COMPACT_ENUM_MAX_MEMBERS = 6
_ARG_ENUM_MAX_MEMBERS = 25
_ANY = "any"
_COMPACT_PRIMITIVES = {
    "string": "str",
    "integer": "int",
    "number": "num",
    "boolean": "bool",
    "null": "null",
}
_ARG_CONSTRAINT_KEYS = (
    "default",
    "format",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
)
_CONSTRAINT_VALUE_MAX_CHARS = 80
# Per-field description caps tried in order: whole, clipped, then omitted.
_ARG_DESCRIPTION_CAPS: tuple[int | None, ...] = (None, 160, 60, 0)
_INDENT = "  "
_LOCAL_REF_PREFIXES = ("#/$defs/", "#/definitions/")
_DEFS_KEYS = ("$defs", "definitions")
_RECURSIVE_REF: dict[str, JsonValue] = {"type": "object"}

_SCHEMA_TRUNCATED_MARKER = "..."
# Progressively shallower renders tried when the full schema exceeds its budget.
_SCHEMA_PRUNE_LEVELS = (3, 2, 1)
_RETURNS_DEPTH_NOTE = "(deeper fields omitted for size; the real data has them)"
_ARGS_DEPTH_NOTE = "(nested fields omitted for size)"


def render_compact_type(node: dict[str, JsonValue]) -> str:
    """A JSON schema as terse type notation, e.g. ``{id:str, tags?:str[]}``."""
    return _compact_type(inline_local_refs(node), _COMPACT_ENUM_MAX_MEMBERS)


def render_compact_type_budgeted(schema: dict[str, JsonValue], budget: int) -> str:
    """Compact type notation within budget, depth-collapsing when oversized."""
    resolved = inline_local_refs(schema)
    rendered = _compact_type(resolved, _COMPACT_ENUM_MAX_MEMBERS)
    if len(rendered) <= budget:
        return rendered
    for levels in _SCHEMA_PRUNE_LEVELS:
        # Pruned properties render as bare `obj`, so depth degrades gracefully.
        pruned = _compact_type(_prune_to_levels(resolved, levels), _COMPACT_ENUM_MAX_MEMBERS)
        if len(pruned) <= budget:
            return f"{pruned}\n{_RETURNS_DEPTH_NOTE}"
    return clip_text(rendered, budget)


def render_args_budgeted(schema: dict[str, JsonValue], budget: int) -> str:
    """Args as ``name?: type  # description [constraints]`` lines within budget."""
    resolved = inline_local_refs(schema)
    for description_cap in _ARG_DESCRIPTION_CAPS:
        rendered = _render_args(resolved, description_cap)
        if len(rendered) <= budget:
            return rendered
    for levels in _SCHEMA_PRUNE_LEVELS:
        pruned = _render_args(cast(dict[str, JsonValue], _prune_to_levels(resolved, levels)), 0)
        if len(pruned) <= budget:
            return f"{pruned}\n{_ARGS_DEPTH_NOTE}"
    # Clipping the shallowest render still shows the top-level fields.
    shallowest_schema = _prune_to_levels(resolved, _SCHEMA_PRUNE_LEVELS[-1])
    shallowest = _render_args(cast(dict[str, JsonValue], shallowest_schema), 0)
    return clip_text(shallowest, budget)


def inline_local_refs(schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Replace local $refs with their definitions; a ref back into its own definition becomes obj."""
    definitions: dict[str, JsonValue] = {}
    for key in _DEFS_KEYS:
        defs = schema.get(key)
        if isinstance(defs, dict):
            definitions.update(defs)
    return cast(dict[str, JsonValue], _inline(schema, definitions, frozenset()))


def _inline(
    node: JsonValue, definitions: dict[str, JsonValue], expanding: frozenset[str]
) -> JsonValue:
    if isinstance(node, list):
        return [_inline(item, definitions, expanding) for item in node]
    if not isinstance(node, dict):
        return node
    rest = {
        key: _inline(value, definitions, expanding)
        for key, value in node.items()
        if key not in _DEFS_KEYS and key != "$ref"
    }
    name = _local_ref_name(node.get("$ref"))
    if name is None or name not in definitions:
        return rest
    if name in expanding:
        return {**_RECURSIVE_REF, **rest}
    target = _inline(definitions[name], definitions, expanding | {name})
    # Siblings of a $ref (a field's own description) override the definition's.
    return {**target, **rest} if isinstance(target, dict) else rest


def _local_ref_name(ref: JsonValue) -> str | None:
    if not isinstance(ref, str):
        return None
    for prefix in _LOCAL_REF_PREFIXES:
        if ref.startswith(prefix):
            return ref.removeprefix(prefix)
    return None


def _prune_to_levels(node: JsonValue, levels: int) -> JsonValue:
    """Depth-limit a JSON schema: nesting past `levels` collapses to a marker."""
    if isinstance(node, list):
        return [_prune_to_levels(item, levels) for item in node]
    if not isinstance(node, dict):
        return node
    pruned: dict[str, JsonValue] = {}
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


def _compact_type(node: object, enum_cap: int) -> str:
    if not isinstance(node, dict):
        return _ANY
    schema: _SchemaNode = cast(_SchemaNode, node)
    variants = _union_variants(schema)
    if variants is not None:
        return _join_arms({_compact_type(variant, enum_cap) for variant in variants})
    obj = _compact_object(schema, enum_cap)
    if obj is not None:
        return obj
    arr = _compact_array(schema, enum_cap)
    if arr is not None:
        return arr
    literal = _compact_literal(schema, enum_cap)
    if literal is not None:
        return literal
    type_ = schema.get("type")
    return _COMPACT_PRIMITIVES.get(str(type_), str(type_) if type_ else _ANY)


def _join_arms(arms: set[str]) -> str:
    # Composio's wrapper adds an empty-schema arm beside the provider's real
    # types; `any|null|str` tells a caller nothing `null|str` does not.
    if len(arms) > 1:
        arms.discard(_ANY)
    return "|".join(sorted(arms))


def _union_variants(node: _SchemaNode) -> list[JsonValue] | None:
    """The members of a union schema (anyOf/oneOf/type-list), else None."""
    variants = node.get("anyOf") or node.get("oneOf")
    if isinstance(variants, list) and variants:
        return variants
    type_ = node.get("type")
    if isinstance(type_, list):
        return [cast(JsonValue, {**node, "type": t}) for t in type_]
    return None


def _is_object(node: _SchemaNode) -> bool:
    type_ = node.get("type")
    return type_ == "object" or (type_ is None and "properties" in node)


def _compact_object(node: _SchemaNode, enum_cap: int) -> str | None:
    """An object schema as ``{name:type, opt?:type, [key]:type}``, else None."""
    if not _is_object(node):
        return None
    properties = node.get("properties")
    required = set(node.get("required") or [])
    fields = [
        f"{name}{'' if name in required else '?'}:{_compact_type(sub, enum_cap)}"
        for name, sub in (properties.items() if isinstance(properties, dict) else ())
    ]
    # A data-keyed map (observed shapes store these as additionalProperties):
    # rendered as an index signature, since the keys are data, not fields.
    additional = node.get("additionalProperties")
    if isinstance(additional, dict):
        fields.append(f"[key]:{_compact_type(additional, enum_cap)}")
    if not fields:
        return "obj"
    return "{" + ", ".join(fields) + "}"


def _compact_array(node: _SchemaNode, enum_cap: int) -> str | None:
    """An array schema as ``item[]`` (grouped when the item is a union), else None."""
    if node.get("type") != "array":
        return None
    item = _compact_type(node.get("items"), enum_cap)
    # Union item types need grouping so {a}|{b}[] cannot misread.
    return (f"({item})" if "|" in item else item) + "[]"


def _compact_literal(node: _SchemaNode, enum_cap: int) -> str | None:
    """A const, or a closed enum within the cap, as JSON members joined by ``|``, else None."""
    if "const" in node:
        return _dumps(node["const"])
    enum = node.get("enum")
    if isinstance(enum, list) and 0 < len(enum) <= enum_cap:
        return "|".join(_dumps(value) for value in enum)
    return None


def _render_args(schema: dict[str, JsonValue], description_cap: int | None) -> str:
    node: _SchemaNode = cast(_SchemaNode, schema)
    if not _has_fields(node):
        return _compact_type(schema, _ARG_ENUM_MAX_MEMBERS)
    return "\n".join(_field_lines(node, 0, description_cap))


def _has_fields(node: _SchemaNode) -> bool:
    properties = node.get("properties")
    return _is_object(node) and isinstance(properties, dict) and bool(properties)


def _field_lines(node: _SchemaNode, depth: int, description_cap: int | None) -> list[str]:
    """One line per field of an object; a field holding an object nests its own lines."""
    properties = cast(dict[str, JsonValue], node.get("properties"))
    required = set(node.get("required") or [])
    indent = _INDENT * depth
    lines: list[str] = []
    for name, sub in properties.items():
        head = f"{indent}{name}{'' if name in required else '?'}: "
        comment = _field_comment(sub, description_cap)
        expansion = _expandable(sub)
        if expansion is None:
            lines.append(f"{head}{_compact_type(sub, _ARG_ENUM_MAX_MEMBERS)}{comment}")
            continue
        prefix, obj, suffix = expansion
        lines.append(f"{head}{prefix}{{{comment}")
        lines.extend(_field_lines(obj, depth + 1, description_cap))
        lines.append(f"{indent}}}{suffix}")
    return lines


def _expandable(node: JsonValue) -> tuple[str, _SchemaNode, str] | None:
    """The object a field nests as lines, with the type text around it, else None."""
    if not isinstance(node, dict):
        return None
    schema: _SchemaNode = cast(_SchemaNode, node)
    variants = _union_variants(schema)
    if variants is not None:
        # Only one object arm can nest: `null|{` reads; two objects would not.
        arms = [(variant, _expandable(variant)) for variant in variants]
        nested = [expansion for _, expansion in arms if expansion is not None]
        if len(nested) != 1:
            return None
        others = {
            _compact_type(v, _ARG_ENUM_MAX_MEMBERS) for v, expansion in arms if expansion is None
        }
        prefix, obj, suffix = nested[0]
        others.discard(_ANY)
        return "".join(f"{other}|" for other in sorted(others)) + prefix, obj, suffix
    if _has_fields(schema):
        return "", schema, ""
    if schema.get("type") == "array":
        item = _expandable(schema.get("items"))
        if item is not None and item[0] == "" and item[2] == "":
            return "", item[1], "[]"
    return None


def _field_comment(node: JsonValue, description_cap: int | None) -> str:
    if not isinstance(node, dict):
        return ""
    parts: list[str] = []
    description = node.get("description")
    if description_cap != 0 and isinstance(description, str) and description.strip():
        text = " ".join(description.split())
        parts.append(text if description_cap is None else clip_text(text, description_cap))
    constraints = _constraints(node)
    if constraints:
        parts.append(f"[{constraints}]")
    return f"  # {' '.join(parts)}" if parts else ""


def _constraints(node: dict[str, JsonValue]) -> str:
    """The validation keywords a caller must satisfy, read off the field and its union arms."""
    found: dict[str, str] = {}
    sources: list[JsonValue] = [node, *(_union_variants(cast(_SchemaNode, node)) or [])]
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in _ARG_CONSTRAINT_KEYS:
            if key in found or key not in source:
                continue
            value = source[key]
            if key == "default" and value is None:
                continue
            # A string default keeps its quotes (it is a value); a format or pattern is read bare.
            text = value if isinstance(value, str) and key != "default" else _dumps(value)
            found[key] = clip_text(text, _CONSTRAINT_VALUE_MAX_CHARS)
    return ", ".join(f"{key}: {text}" for key, text in found.items())


def _dumps(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)
