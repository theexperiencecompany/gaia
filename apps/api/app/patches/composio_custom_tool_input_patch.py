# Coerce LangChain-side lookalike instances to plain data before Composio's
# real input validation.
"""Why this patch exists (read before touching).

Every custom tool's input has two Pydantic identities: the REAL model from the
decorated function's request annotation, which CustomTool.invoke_trusted
validates against, and a LOOKALIKE rebuilt from JSON schema that Composio installs
as the LangChain tool's args_schema. LangChain hands lookalike instances down the
chain and the real model's isinstance check then rejects them. Plain dicts
validate against either class, so coercing everything to plain data at this one
boundary fixes every nested-model custom tool on every path, with no special cases.
"""

import typing as t

from pydantic import BaseModel

from app.constants.log_tags import LogTag
from shared.py.wide_events import log


def to_plain_data(obj: t.Any) -> t.Any:  # noqa: ANN401 -- recursive JSON-ish tree, genuinely schemaless
    """Deep-convert lookalike model instances to plain JSON-ish data.

    model_dump(mode="json") recurses fully, so one call per model is enough;
    containers recurse element-wise; everything else passes through untouched.
    """
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {key: to_plain_data(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain_data(value) for value in obj]
    return obj


_original_invoke_trusted: t.Any = None
_applied = False


def _coercing_invoke_trusted(self: t.Any, user_id: str, request_kwargs: t.Any) -> t.Any:  # noqa: ANN401 -- mirrors Composio's untyped boundary
    """Run CustomTool.invoke_trusted with lookalike instances coerced first."""
    return _original_invoke_trusted(self, user_id, to_plain_data(request_kwargs))


t.cast(
    t.Any, _coercing_invoke_trusted
).__gaia_coercing__ = True  # marker for tests: this wrapper is ours, not Composio's


def apply() -> None:
    """Wrap CustomTool.invoke_trusted exactly once (idempotent)."""
    global _applied, _original_invoke_trusted
    if _applied:
        return
    try:
        from composio.core.models.custom_tools import (  # noqa: PLC0415 -- upstream import stays inside apply() so failures log instead of breaking app import
            CustomTool,
        )

        _original_invoke_trusted = CustomTool.invoke_trusted
        # Lets inspect.unwrap (and debuggers) see through to the real dispatch.
        t.cast(t.Any, _coercing_invoke_trusted).__wrapped__ = _original_invoke_trusted
        CustomTool.invoke_trusted = _coercing_invoke_trusted  # type: ignore[method-assign]  # rebinding an upstream method is what a monkey-patch is; mypy rejects it by design
        _applied = True
        log.info(
            f"{LogTag.PATCH} Applied custom_tool input coercion patch",
            patch="composio_custom_tool_input",
        )
    except Exception as e:
        log.error(
            f"{LogTag.PATCH} Failed to apply custom_tool input patch",
            patch="composio_custom_tool_input",
            error=str(e),
            error_type=type(e).__name__,
        )
