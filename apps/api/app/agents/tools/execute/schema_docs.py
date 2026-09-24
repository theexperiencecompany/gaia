"""Render a tool's contract as a compact text doc for the model.

This is what replaces bind_tools for proxied tools: the model reads this doc
and constructs `data` for execute() from it. Docs carry args only, as compact
field lines budgeted by schema_notation. Return shapes are
deliberately NOT in discovery docs: they are explored on demand through
get_tool_schema (host) or gaia.schema/the tool-docs files (sandbox), so the
context pays for a shape only when something actually consumes it.
"""

from typing import cast

from langchain_core.tools import BaseTool
from pydantic import BaseModel, JsonValue

from app.agents.tools.execute.schema_notation import _SchemaNode, render_args_budgeted
from app.constants.execute import (
    ARGS_SCHEMA_MAX_CHARS,
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
    """One tool's usage doc: description and args. Never the returns."""
    lines = [f"## {tool.name}"]
    description = tool.description.strip()
    if description:
        lines.append(clip_text(description, _DESCRIPTION_MAX_CHARS))
    lines.append(f"Args for {EXECUTE_TOOL_NAME}(tool_name=..., data={{...}}), ? = optional:")
    lines.append(render_args_budgeted(_args_schema_of(tool), ARGS_SCHEMA_MAX_CHARS))
    lines.append(
        f'Run it with: {EXECUTE_TOOL_NAME}(task_description="...", '
        f'tool_name="{tool.name}", data={{...}})'
    )
    return clip_text("\n".join(lines), SCHEMA_DOC_MAX_CHARS)


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
