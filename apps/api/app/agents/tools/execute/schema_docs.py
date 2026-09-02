"""Render a tool's contract as a compact text doc for the model.

This is what replaces bind_tools for proxied tools: the model reads this doc
and constructs `data` for execute() from it. Two hard rules from the spike:
return shapes are documented ONLY when the provider supplies one (never
invented), and every schema is budgeted — a multi-thousand-token schema
degrades to shallower levels instead of being injected wholesale or clipped
mid-JSON.
"""

import json
from typing import Any, cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel

from app.constants.execute import (
    ARGS_SCHEMA_MAX_CHARS,
    EXECUTE_TOOL_NAME,
    RESPONSE_SCHEMA_MAX_CHARS,
    RESPONSE_SCHEMA_METADATA_KEYS,
    SCHEMA_DOC_MAX_CHARS,
)
from app.utils.general_utils import clip_text

# Composio's wrapper injects a config-passthrough parameter into the synthesized
# signature; it is plumbing, never something the model supplies.
_INTERNAL_ARG_NAMES = {"__runnable_config__"}
_DESCRIPTION_MAX_CHARS = 600


def render_tool_doc(tool: BaseTool) -> str:
    """One tool's usage doc: description, args schema, returns (when known)."""
    lines = [f"## {tool.name}"]
    description = (tool.description or "").strip()
    if description:
        lines.append(clip_text(description, _DESCRIPTION_MAX_CHARS))
    lines.append("Args schema for execute(tool_name=..., data={...}):")
    lines.append(_render_budgeted_schema(_args_schema_of(tool), ARGS_SCHEMA_MAX_CHARS))
    returns = _response_schema_of(tool)
    if returns is not None:
        lines.append("Returns:")
        lines.append(_render_budgeted_schema(returns, RESPONSE_SCHEMA_MAX_CHARS))
    lines.append(
        f'Run it with: {EXECUTE_TOOL_NAME}(task_description="...", '
        f'tool_name="{tool.name}", data={{...}})'
    )
    return clip_text("\n".join(lines), SCHEMA_DOC_MAX_CHARS)


def _args_schema_of(tool: BaseTool) -> dict[str, Any]:
    schema = getattr(tool, "args_schema", None)
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        raw = schema.model_json_schema()
    elif isinstance(schema, dict):
        raw = dict(schema)
    else:
        raw = {"type": "object", "properties": {}}
    return _compact_schema(raw)


def _response_schema_of(tool: BaseTool) -> dict[str, Any] | None:
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return None
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


def _render_budgeted_schema(schema: dict[str, Any], budget: int) -> str:
    """One schema section within budget: full, depth-pruned, or names-only."""
    full = _dumps(schema)
    if len(full) <= budget:
        return full
    for levels in _SCHEMA_PRUNE_LEVELS:
        pruned = _dumps(_prune_to_levels(schema, levels))
        if len(pruned) <= budget:
            return f"{pruned}\n{_SCHEMA_TRUNCATION_NOTE}"
    properties = schema.get("properties")
    names = sorted(properties) if isinstance(properties, dict) else []
    floor = _dumps({"type": schema.get("type", "object"), "fields": names})
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
        elif key == "items" and isinstance(value, dict | list):
            pruned[key] = (
                _prune_to_levels(value, levels - 1) if levels > 0 else _SCHEMA_TRUNCATED_MARKER
            )
        else:
            pruned[key] = _prune_to_levels(value, levels)
    return pruned


def _dumps(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _compact_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Strip generator noise (titles, internal params, $defs plumbing keys)."""
    # cast, not isinstance: _strip_noise maps dict->dict by construction.
    compacted = cast(dict[str, Any], _strip_noise(schema))
    properties = compacted.get("properties")
    if isinstance(properties, dict):
        for name in _INTERNAL_ARG_NAMES:
            properties.pop(name, None)
        if isinstance(compacted.get("required"), list):
            compacted["required"] = [
                r for r in compacted["required"] if r not in _INTERNAL_ARG_NAMES
            ]
    return compacted


def _strip_noise(node: Any) -> Any:  # noqa: ANN401 -- recursive JSON tree, genuinely schemaless
    if isinstance(node, dict):
        return {key: _strip_noise(value) for key, value in node.items() if key not in {"title"}}
    if isinstance(node, list):
        return [_strip_noise(item) for item in node]
    return node
