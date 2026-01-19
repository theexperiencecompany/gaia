"""
Patch for Composio CustomTool to inline $ref references in schemas.

Uses jsonref.replace_refs() to resolve all JSON Schema $ref references.
"""

import typing as t

import jsonref


def to_std_dict(obj: t.Any) -> t.Any:
    """Recursively convert jsonref proxies to standard python dicts/lists"""
    if isinstance(obj, dict):
        return {k: to_std_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [to_std_dict(elem) for elem in obj]
    return obj


_original_parse_info = None
_applied = False


def _patched_parse_info(self):
    """Patched version that inlines $ref before storing schema"""
    tool_info = _original_parse_info(self)

    if hasattr(tool_info, "input_parameters") and isinstance(
        tool_info.input_parameters, dict
    ):
        # Use jsonref to inline all $ref references
        resolved = jsonref.replace_refs(tool_info.input_parameters)
        # Convert back to standard dict to avoid jsonref.JsonRef proxy issues
        tool_info.input_parameters = to_std_dict(resolved)

    return tool_info


def apply():
    """Apply the patch to CustomTool.__parse_info"""
    global _applied, _original_parse_info

    if _applied:
        return

    try:
        from composio.core.models.custom_tools import CustomTool

        _original_parse_info = CustomTool._CustomTool__parse_info
        CustomTool._CustomTool__parse_info = _patched_parse_info

        _applied = True
        print("[PATCH] Applied custom_tool schema inline patch using jsonref")
    except Exception as e:
        print(f"[PATCH] Failed to apply custom_tool patch: {e}")


# Apply patch
apply()
