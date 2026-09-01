"""Render a tool's contract as a compact text doc for the model.

This is what replaces bind_tools for proxied tools: the model reads this doc
and constructs `data` for execute() from it. Two hard rules from the spike:
return shapes are documented ONLY when the provider supplies one (never
invented), and the whole doc is capped — a multi-thousand-token response
schema must never be injected wholesale.
"""

import json
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel

from app.constants.execute import (
    EXECUTE_TOOL_NAME,
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
    lines.append(json.dumps(_args_schema_of(tool), separators=(",", ":"), default=str))
    returns = _response_schema_of(tool)
    if returns is not None:
        lines.append("Returns:")
        lines.append(json.dumps(returns, separators=(",", ":"), default=str))
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


def _compact_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Strip generator noise (titles, internal params, $defs plumbing keys)."""
    compacted = _strip_noise(schema)
    properties = compacted.get("properties")
    if isinstance(properties, dict):
        for name in _INTERNAL_ARG_NAMES:
            properties.pop(name, None)
        if isinstance(compacted.get("required"), list):
            compacted["required"] = [
                r for r in compacted["required"] if r not in _INTERNAL_ARG_NAMES
            ]
    return compacted


def _strip_noise(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _strip_noise(value) for key, value in node.items() if key not in {"title"}}
    if isinstance(node, list):
        return [_strip_noise(item) for item in node]
    return node
