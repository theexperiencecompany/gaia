"""Describe a gated call in plain words: what it does, to whom, and the few facts that matter.

Deterministic (no LLM in the gate's hot path). One description feeds the web card,
the bot prompt, the reply classifier and the model-facing summary, so every surface
states the same facts.
"""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from app.constants.hil_descriptions import (
    HIL_DEFAULT_CONFIRM,
    HIL_DESCRIPTION_MAX_DETAILS,
    HIL_DESCRIPTION_MAX_LIST_ITEMS,
    HIL_DESCRIPTION_PREVIEW_CHARS,
    HIL_DESCRIPTION_VALUE_CHARS,
    HIL_TOOL_DESCRIPTIONS,
    DetailField,
    DetailRole,
    ToolDescription,
)
from app.constants.tool_labels import clean_tool_slug
from app.models.hil_models import ApprovalDescription, ApprovalDetail
from app.utils.general_utils import clip_text

_Scalar = str | int | float | bool


class _BrowserTaskArgs(BaseModel):
    """The one browser_task argument the description reads."""

    model_config = ConfigDict(extra="ignore")

    task: str = ""


def describe_call(
    tool_name: str,
    args: Mapping[str, object],
    integration_name: str | None,
    account: str | None = None,
) -> ApprovalDescription:
    """Describe one gated call; tools with no curated entry get a humanised fallback."""
    if tool_name == "browser_task":
        return _describe_browser_task(args)
    spec = HIL_TOOL_DESCRIPTIONS.get(tool_name)
    if spec is None:
        action = clean_tool_slug(tool_name, integration_name).capitalize()
        if integration_name:
            action = f"{action} in {integration_name}"
        spec = ToolDescription(action=action, confirm=HIL_DEFAULT_CONFIRM)
    details = _curated_details(spec, args) if spec.fields else _fallback_details(args)
    headline = _headline(spec, args)
    if not spec.fields and details:
        # No curated target to name, so the first argument stands in for it.
        headline += f": {details[0].value}"
    if account:
        headline += f" (as {account})"
    return ApprovalDescription(
        action=spec.action,
        headline=headline,
        confirm=spec.confirm,
        details=details[:HIL_DESCRIPTION_MAX_DETAILS],
    )


def _describe_browser_task(args: Mapping[str, object]) -> ApprovalDescription:
    """Describe a browser task by its task text: the first sentence, or a clipped lead."""
    task = _BrowserTaskArgs.model_validate(args).task.strip()
    action = "Start a browser task"
    if not task:
        return ApprovalDescription(action=action, headline=action, confirm="start it", details=[])
    first = task.split(". ")[0].strip().rstrip(".")
    concise = first if 0 < len(first) <= 140 else clip_text(task, 140)
    return ApprovalDescription(
        action=action,
        headline=f"{action}: {concise}",
        confirm="start it",
        details=[ApprovalDetail(label="Task", value=_preview(task))],
    )


def _headline(spec: ToolDescription, args: Mapping[str, object]) -> str:
    """Join the action to its target, e.g. Send an email to bob@x.com: "Q3 numbers"."""
    headline = spec.action
    by_role = {f.role: _field_value(f, args) for f in spec.fields}
    if recipients := by_role.get(DetailRole.RECIPIENTS):
        headline += f" to {recipients}"
    if place := by_role.get(DetailRole.PLACE):
        headline += f" {spec.place_word} {place}"
    if title := by_role.get(DetailRole.TITLE):
        headline += f': "{title}"'
    return headline


def _curated_details(spec: ToolDescription, args: Mapping[str, object]) -> list[ApprovalDetail]:
    details: list[ApprovalDetail] = []
    for field in spec.fields:
        value = _field_value(field, args)
        if value:
            details.append(ApprovalDetail(label=field.label, value=value))
    return details


def _field_value(field: DetailField, args: Mapping[str, object]) -> str | None:
    """Join every listed key's values, so a main recipient plus extras read as one list."""
    items: list[str] = []
    for key in field.keys:
        items.extend(_items(args.get(key)))
    if not items:
        return None
    if field.role is DetailRole.CONTENT:
        return f'"{_preview(" ".join(items))}"'
    return _join(items)


def _fallback_details(args: Mapping[str, object]) -> list[ApprovalDetail]:
    """Show short scalar and list arguments under humanised names, for tools with no entry."""
    details: list[ApprovalDetail] = []
    for key, raw in args.items():
        items = _items(raw)
        if items:
            details.append(ApprovalDetail(label=_humanise_key(key), value=_join(items)))
    return details


def _items(value: object) -> list[str]:
    """Return a scalar or a list of scalars as display strings; anything nested shows nothing."""
    if isinstance(value, _Scalar) and str(value).strip():
        return [str(value).strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if isinstance(v, _Scalar) and str(v).strip()]
    return []


def _join(items: list[str]) -> str:
    shown = [clip_text(item, HIL_DESCRIPTION_VALUE_CHARS) for item in items]
    if len(shown) <= HIL_DESCRIPTION_MAX_LIST_ITEMS:
        return ", ".join(shown)
    rest = len(shown) - HIL_DESCRIPTION_MAX_LIST_ITEMS
    return f"{', '.join(shown[:HIL_DESCRIPTION_MAX_LIST_ITEMS])} and {rest} more"


def _preview(text: str) -> str:
    return clip_text(" ".join(text.split()), HIL_DESCRIPTION_PREVIEW_CHARS)


def _humanise_key(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()
