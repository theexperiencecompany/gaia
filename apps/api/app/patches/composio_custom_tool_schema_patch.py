"""
Patch for Composio CustomTool to inline $ref references in schemas.

Uses jsonref.replace_refs() to resolve all JSON Schema $ref references.
"""

from collections.abc import Callable
import typing as t

import jsonref

from app.constants.log_tags import LogTag
from shared.py.wide_events import log


def to_std_dict(obj: t.Any) -> t.Any:  # noqa: ANN401 -- framework contract
    """Recursively convert jsonref proxies to standard python dicts/lists"""
    if isinstance(obj, dict):
        return {k: to_std_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_std_dict(elem) for elem in obj]
    return obj


_original_parse_info: Callable[..., t.Any] | None = None
_applied = False


def _patched_parse_info(self: t.Any) -> t.Any:  # noqa: ANN401 -- framework contract
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
        from composio.core.models.custom_tools import (  # noqa: PLC0415 -- upstream import stays inside apply() so failures log instead of breaking app import
            CustomTool,
        )

        # Name-mangled private attribute (CustomTool.__parse_info) isn't a
        # public attribute mypy can resolve on the class; the cast to Any
        # describes that to the type checker without changing the access itself.
        custom_tool_cls = t.cast(t.Any, CustomTool)
        _original_parse_info = custom_tool_cls._CustomTool__parse_info
        custom_tool_cls._CustomTool__parse_info = _patched_parse_info

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
