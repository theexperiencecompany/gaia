"""
Patch for Composio CustomTool to inline $ref references in schemas.

Uses jsonref.replace_refs() to resolve all JSON Schema $ref references.
"""

from collections.abc import Callable
import typing as t

import jsonref

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

if t.TYPE_CHECKING:
    from composio.core.models.custom_tools import CustomTool
    from composio_client.types.tool_list_response import Item

# Name-mangled private attribute (CustomTool.__parse_info) isn't a public
# attribute mypy can resolve on the class; the mangled string is the runtime
# spell the patch needs, so access it dynamically (see apply()).
_PARSE_INFO_MANGLED_NAME = "_CustomTool__parse_info"


@t.overload
def to_std_dict(obj: dict[str, object]) -> dict[str, object]: ...
@t.overload
def to_std_dict(obj: list[object]) -> list[object]: ...
@t.overload
def to_std_dict(obj: object) -> object: ...
def to_std_dict(obj: object) -> object:
    """Recursively convert jsonref proxies to standard python dicts/lists"""
    if isinstance(obj, dict):
        return {k: to_std_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_std_dict(elem) for elem in obj]
    return obj


_original_parse_info: "Callable[[CustomTool], Item] | None" = None
_applied = False


def _patched_parse_info(self: "CustomTool") -> "Item":
    """Patched version that inlines $ref before storing schema"""
    if _original_parse_info is None:
        raise RuntimeError("composio_custom_tool_schema_patch.apply() was not called")
    tool_info = _original_parse_info(self)

    if hasattr(tool_info, "input_parameters") and isinstance(tool_info.input_parameters, dict):
        # Use jsonref to inline all $ref references
        resolved = jsonref.replace_refs(tool_info.input_parameters)
        # Convert back to standard dict to avoid jsonref.JsonRef proxy issues
        tool_info.input_parameters = to_std_dict(resolved)

    return tool_info


def apply() -> None:
    """Apply the patch to CustomTool.__parse_info"""
    global _applied, _original_parse_info

    if _applied:
        return

    try:
        from composio.core.models.custom_tools import CustomTool

        _original_parse_info = getattr(CustomTool, _PARSE_INFO_MANGLED_NAME)
        setattr(CustomTool, _PARSE_INFO_MANGLED_NAME, _patched_parse_info)

        _applied = True
        log.info(
            f"{LogTag.PATCH} Applied custom_tool schema inline patch", patch="custom_tool_schema"
        )
    except Exception as e:
        log.error(
            f"{LogTag.PATCH} Failed to apply custom_tool patch",
            patch="custom_tool_schema",
            error=str(e),
            error_type=type(e).__name__,
        )


# Apply patch
apply()
