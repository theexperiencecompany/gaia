"""Schema normalization utilities for MCP tool conversion.

Some MCP servers return schemas with edge cases that cause conversion issues.
This module provides utilities to normalize schemas before conversion.
"""

from mcp.types import Tool

from app.constants.log_tags import LogTag
from shared.py.wide_events import log


def normalize_schema_refs(schema: object) -> object:
    """Normalize $ref references in a JSON schema.

    Some MCP servers use numeric keys in $defs (like '0', '1') which can cause
    issues with reference resolution. This function normalizes such schemas.

    ``schema`` is typed ``object``, not ``dict``, because some MCP servers hand
    back a non-dict ``inputSchema`` (bool/None/etc.) — the isinstance guard
    below is a real, load-bearing check, not dead code.

    Args:
        schema: JSON schema value (expected to be a dict, but not guaranteed)

    Returns:
        Normalized schema with fixed $refs, or the original value unchanged
        when it isn't a dict
    """
    log.set(operation="normalize_schema_refs")
    if not isinstance(schema, dict):
        return schema

    schema = schema.copy()

    # Check if schema has $defs or definitions
    defs_key = None
    if "$defs" in schema:
        defs_key = "$defs"
    elif "definitions" in schema:
        defs_key = "definitions"

    if defs_key and schema[defs_key]:
        # Check if any keys are numeric strings
        numeric_keys = [k for k in schema[defs_key] if k.isdigit()]

        if numeric_keys:
            log.warning(
                f"{LogTag.STARTUP} Found numeric definition keys: . This can cause $ref resolution issues. Normalizing...",
                numeric_keys=numeric_keys,
            )

            # Create new definitions with prefixed keys
            new_defs = {}
            key_mapping = {}

            for old_key, value in schema[defs_key].items():
                if old_key.isdigit():
                    new_key = f"Def{old_key}"
                    new_defs[new_key] = value
                    key_mapping[old_key] = new_key
                    log.debug(
                        f"{LogTag.STARTUP} Renamed definition key", old_key=old_key, new_key=new_key
                    )
                else:
                    new_defs[old_key] = value

            schema[defs_key] = new_defs

            # Update all $refs to use new keys
            _update_refs_recursive(schema, key_mapping, defs_key)

    return schema


def _update_refs_recursive(obj: object, key_mapping: dict[str, str], defs_key: str) -> None:
    """Recursively update $ref values in a schema.

    Args:
        obj: Object to update (dict, list, or primitive)
        key_mapping: Mapping of old keys to new keys
        defs_key: The definitions key ('$defs' or 'definitions')
    """
    if isinstance(obj, dict):
        # Check if this object has a $ref
        if "$ref" in obj:
            ref = obj["$ref"]
            # Parse ref like "#/$defs/0" or "#/definitions/0"
            if ref.startswith(f"#/{defs_key}/"):
                ref_key = ref.split("/")[-1]
                if ref_key in key_mapping:
                    new_ref = f"#/{defs_key}/{key_mapping[ref_key]}"
                    obj["$ref"] = new_ref
                    log.debug(f"{LogTag.STARTUP} Updated $ref", ref=ref, new_ref=new_ref)

        # Recurse into dict values
        for value in obj.values():
            _update_refs_recursive(value, key_mapping, defs_key)

    elif isinstance(obj, list):
        # Recurse into list items
        for item in obj:
            _update_refs_recursive(item, key_mapping, defs_key)


def patch_tool_schema(tool: Tool) -> Tool:
    """Patch a tool's input schema to fix common issues.

    Args:
        tool: MCP tool object with inputSchema attribute

    Returns:
        Tool with normalized schema
    """
    log.set(operation="patch_tool_schema", tool_name=getattr(tool, "name", None))
    if not hasattr(tool, "inputSchema") or not tool.inputSchema:
        return tool

    # Normalize the schema
    try:
        normalized = normalize_schema_refs(tool.inputSchema)
        if normalized != tool.inputSchema:
            log.info(f"{LogTag.STARTUP} Normalized schema for tool", name=tool.name)
            # Create a modified copy
            tool_dict = tool.model_dump()
            tool_dict["inputSchema"] = normalized
            return type(tool)(**tool_dict)
    except Exception as e:
        log.warning(
            f"{LogTag.STARTUP} Could not normalize schema for tool : . Using original schema.",
            name=tool.name,
            error=str(e),
            error_type=type(e).__name__,
        )

    return tool
