"""Schema normalization utilities for MCP tool conversion.

Some MCP servers return schemas with edge cases that cause conversion issues.
This module provides utilities to normalize schemas before conversion.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def normalize_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize $ref references in a JSON schema.

    Some MCP servers use numeric keys in $defs (like '0', '1') which can cause
    issues with reference resolution. This function normalizes such schemas.

    Args:
        schema: JSON schema dict

    Returns:
        Normalized schema with fixed $refs
    """
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
        numeric_keys = [k for k in schema[defs_key].keys() if k.isdigit()]

        if numeric_keys:
            logger.warning(
                f"Found numeric definition keys: {numeric_keys}. "
                f"This can cause $ref resolution issues. Normalizing..."
            )

            # Create new definitions with prefixed keys
            new_defs = {}
            key_mapping = {}

            for old_key, value in schema[defs_key].items():
                if old_key.isdigit():
                    new_key = f"Def{old_key}"
                    new_defs[new_key] = value
                    key_mapping[old_key] = new_key
                    logger.debug(f"Renamed definition key: '{old_key}' -> '{new_key}'")
                else:
                    new_defs[old_key] = value

            schema[defs_key] = new_defs

            # Update all $refs to use new keys
            _update_refs_recursive(schema, key_mapping, defs_key)

    return schema


def _update_refs_recursive(
    obj: Any, key_mapping: dict[str, str], defs_key: str
) -> None:
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
                    logger.debug(f"Updated $ref: '{ref}' -> '{new_ref}'")

        # Recurse into dict values
        for value in obj.values():
            _update_refs_recursive(value, key_mapping, defs_key)

    elif isinstance(obj, list):
        # Recurse into list items
        for item in obj:
            _update_refs_recursive(item, key_mapping, defs_key)


def patch_tool_schema(tool: Any) -> Any:
    """Patch a tool's input schema to fix common issues.

    Args:
        tool: MCP tool object with inputSchema attribute

    Returns:
        Tool with normalized schema
    """
    if not hasattr(tool, "inputSchema") or not tool.inputSchema:
        return tool

    # Normalize the schema
    try:
        normalized = normalize_schema_refs(tool.inputSchema)
        if normalized != tool.inputSchema:
            logger.info(f"Normalized schema for tool: {tool.name}")
            # Create a modified copy
            tool_dict = tool.model_dump()
            tool_dict["inputSchema"] = normalized
            return type(tool)(**tool_dict)
    except Exception as e:
        logger.warning(
            f"Could not normalize schema for tool {tool.name}: {e}. "
            f"Using original schema."
        )

    return tool
