"""Describe a gated call in plain words: one natural sentence and the few facts that matter.

Deterministic (no LLM in the gate's hot path). One description feeds the web card,
the bot prompt, the reply classifier and the model-facing summary, so every surface
states the same facts. Dates read in the user's zone, relative to now.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from string import Formatter

from pydantic import BaseModel, ConfigDict

from app.constants.connectors import RUN_CONNECTOR_TOOL
from app.constants.hil_descriptions import (
    HIL_CHANGE_JOIN,
    HIL_CHANGE_LEAD,
    HIL_DEFAULT_ASK,
    HIL_DEFAULT_CONFIRM,
    HIL_DESCRIPTION_MAX_DETAILS,
    HIL_DESCRIPTION_MAX_LIST_ITEMS,
    HIL_DESCRIPTION_PREVIEW_CHARS,
    HIL_DESCRIPTION_VALUE_CHARS,
    HIL_FALLBACK_TITLE_KEYS,
    HIL_REASK,
    HIL_SENTENCE_ROLES,
    HIL_TOOL_DESCRIPTIONS,
    DetailField,
    DetailRole,
    ToolDescription,
)
from app.constants.tool_labels import clean_tool_slug
from app.models.hil_models import ApprovalDescription, ApprovalDetail
from app.services.hil.when import UserClock, parse_moment, say_moment
from app.utils.general_utils import clip_text

_Scalar = str | int | float
# A field key "events[].summary" reads summary from every item of the events list.
_EACH = "[]."
_BROWSER_ACTION = "Start a browser task"
_BROWSER_LEAD_CHARS = 140
# How much of a connector call's command line the approval card's headline shows.
_CONNECTOR_COMMAND_CHARS = 140


class _BrowserTaskArgs(BaseModel):
    """The one browser_task argument the description reads."""

    model_config = ConfigDict(extra="ignore")

    task: str = ""


@dataclass(frozen=True)
class _Fact:
    """One field's display values, before it becomes a sentence slot or a detail line."""

    label: str
    role: DetailRole
    items: tuple[str, ...]

    def detail(self) -> ApprovalDetail:
        text = " ".join(self.items)
        long_single = len(self.items) == 1 and len(text) > HIL_DESCRIPTION_VALUE_CHARS
        if self.role is DetailRole.CONTENT or long_single:
            return ApprovalDetail(label=self.label, value=_quote(_preview(text)), expandable=True)
        return ApprovalDetail(label=self.label, value=_join(self.items))


def describe_call(
    tool_name: str,
    args: Mapping[str, object],
    integration_name: str | None,
    account: str | None = None,
    amended_args: Mapping[str, object] | None = None,
    *,
    clock: UserClock,
) -> ApprovalDescription:
    """Describe one gated call; tools with no curated entry get a humanised fallback.

    amended_args is the call the user approved with a change; the facts that differ from it
    are the changes, and the question leads with them.
    """
    if tool_name == "browser_task":
        return _describe_browser_task(args)
    if tool_name == RUN_CONNECTOR_TOOL:
        return _describe_connector_call(args, integration_name)
    spec = _spec(tool_name, args, integration_name)
    facts = _facts(spec, args, clock)
    phrase = _phrase(spec, facts)
    if account:
        phrase += f" as {account}"
    changes = [] if amended_args is None else _changed(facts, _facts(spec, amended_args, clock))
    change_note = _change_note(changes)
    return ApprovalDescription(
        action=spec.action,
        headline=_capitalise(phrase),
        question=(
            HIL_REASK.format(change=change_note, confirm=spec.confirm)
            if change_note
            else f"{spec.ask} {phrase}?"
        ),
        confirm=spec.confirm,
        details=[f.detail() for f in facts if f.role not in HIL_SENTENCE_ROLES][
            :HIL_DESCRIPTION_MAX_DETAILS
        ],
        changes=changes,
        change_note=change_note,
    )


def describe_action(tool_name: str, integration_name: str | None) -> str:
    """Name the kind of action a tool takes, e.g. Send an email, without reading its arguments."""
    if tool_name == "browser_task":
        return _BROWSER_ACTION
    return _spec(tool_name, {}, integration_name).action


def _spec(
    tool_name: str, args: Mapping[str, object], integration_name: str | None
) -> ToolDescription:
    """Return the curated phrasing, or one built from the slug and arguments."""
    curated = HIL_TOOL_DESCRIPTIONS.get(tool_name)
    if curated is not None:
        return curated
    words = clean_tool_slug(tool_name, integration_name).lower()
    place = f" in {integration_name}" if integration_name else ""
    title_key = next((key for key in HIL_FALLBACK_TITLE_KEYS if _values(args, key)), None)
    fields = tuple(
        DetailField(
            _humanise_key(key),
            (key,),
            DetailRole.TITLE if key == title_key else DetailRole.OTHER,
        )
        for key in args
        if not _is_hidden_key(key)
    )
    return ToolDescription(
        action=_capitalise(f"{words}{place}"),
        phrase=(words, " {title}", place),
        confirm=HIL_DEFAULT_CONFIRM,
        fields=fields,
    )


def _facts(spec: ToolDescription, args: Mapping[str, object], clock: UserClock) -> list[_Fact]:
    facts: list[_Fact] = []
    for field in spec.fields:
        items = [_say(item, field.role, clock) for key in field.keys for item in _values(args, key)]
        if items:
            facts.append(_Fact(field.label, field.role, tuple(items)))
    return facts


def _say(item: str, role: DetailRole, clock: UserClock) -> str:
    """Humanise a date or time; content is never read as one."""
    if role is DetailRole.CONTENT:
        return item
    moment = parse_moment(item)
    return item if moment is None else say_moment(moment, clock)


def _phrase(spec: ToolDescription, facts: list[_Fact]) -> str:
    """Fill the sentence parts, leaving out any part whose slot has no value."""
    slots: dict[str, str] = {}
    for fact in facts:
        if fact.role in HIL_SENTENCE_ROLES:
            slot = _join(fact.items, quoted=fact.role is DetailRole.TITLE)
            slots.setdefault(fact.role.value, slot)
    parts: list[str] = []
    for part in spec.phrase:
        names = [name for _, name, _, _ in Formatter().parse(part) if name]
        if not names:
            parts.append(part)
        elif all(name in slots for name in names):
            parts.append(part.format_map(slots))
    return "".join(parts)


def _changed(facts: list[_Fact], before: list[_Fact]) -> list[ApprovalDetail]:
    """Return the facts whose value the change set or moved."""
    was = {fact.label: fact.detail().value for fact in before}
    return [fact.detail() for fact in facts if was.get(fact.label) != fact.detail().value]


def _change_note(changes: list[ApprovalDetail]) -> str | None:
    if not changes:
        return None
    said = HIL_CHANGE_JOIN.join(f"{_lower_first(c.label)} to {c.value}" for c in changes)
    return f"{HIL_CHANGE_LEAD} {said}"


def _describe_browser_task(args: Mapping[str, object]) -> ApprovalDescription:
    """Describe a browser task by its task text: the first sentence, or a clipped lead."""
    task = _BrowserTaskArgs.model_validate(args).task.strip()
    question = f"{HIL_DEFAULT_ASK} {_lower_first(_BROWSER_ACTION)}?"
    if not task:
        return ApprovalDescription(
            action=_BROWSER_ACTION,
            headline=_BROWSER_ACTION,
            question=question,
            confirm="start it",
            details=[],
        )
    first = task.split(". ")[0].strip().rstrip(".")
    concise = (
        first if 0 < len(first) <= _BROWSER_LEAD_CHARS else clip_text(task, _BROWSER_LEAD_CHARS)
    )
    return ApprovalDescription(
        action=_BROWSER_ACTION,
        headline=f"{_BROWSER_ACTION}: {concise}",
        question=question,
        confirm="start it",
        details=[ApprovalDetail(label="Task", value=_preview(task))],
    )


class _ConnectorCallArgs(BaseModel):
    """The run_connector arguments the description reads."""

    model_config = ConfigDict(extra="ignore")

    argv: list[str] = []


def _describe_connector_call(
    args: Mapping[str, object], connector: str | None
) -> ApprovalDescription:
    """Describe a connector call by the command it runs, on the connector the user named."""
    command = clip_text(
        " ".join(_ConnectorCallArgs.model_validate(args).argv), _CONNECTOR_COMMAND_CHARS
    )
    place = f" on {connector}" if connector else ""
    phrase = f"run {command}{place}" if command else f"run a command{place}"
    return ApprovalDescription(
        action=_capitalise(f"run a command{place}"),
        headline=_capitalise(phrase),
        question=f"{HIL_DEFAULT_ASK} {phrase}?",
        confirm=HIL_DEFAULT_CONFIRM,
        details=[],
    )


def _values(args: Mapping[str, object], key: str) -> list[str]:
    """Read a key's display strings; events[].summary reads summary from each list item."""
    if _EACH not in key:
        return _items(args.get(key))
    # The one key with []. (events[].summary) splits alike under rsplit or any maxsplit.
    list_key, sub_key = key.split(_EACH, 1)  # pragma: no mutate
    rows = args.get(list_key)
    if not isinstance(rows, list):
        return []
    return [item for row in rows if isinstance(row, Mapping) for item in _items(row.get(sub_key))]


def _items(value: object) -> list[str]:
    """Return a scalar or a list of scalars as display strings; nested, blank or false shows nothing."""
    if isinstance(value, bool):
        return ["Yes"] if value else []
    if isinstance(value, _Scalar) and str(value).strip():
        return [str(value).strip()]
    if isinstance(value, list):
        return [item for v in value if not isinstance(v, list | dict) for item in _items(v)]
    return []


def _is_hidden_key(key: str) -> bool:
    """Ids and timezone fields mean nothing to the person deciding."""
    lowered = key.lower()
    return lowered == "id" or lowered.endswith(("_id", "_ids", "_tz")) or "timezone" in lowered


def _join(items: tuple[str, ...] | list[str], quoted: bool = False) -> str:
    shown = [clip_text(item, HIL_DESCRIPTION_VALUE_CHARS) for item in items]
    if quoted:
        shown = [_quote(item) for item in shown]
    if len(shown) <= HIL_DESCRIPTION_MAX_LIST_ITEMS:
        return ", ".join(shown)
    rest = len(shown) - HIL_DESCRIPTION_MAX_LIST_ITEMS
    return f"{', '.join(shown[:HIL_DESCRIPTION_MAX_LIST_ITEMS])} and {rest} more"


def _quote(text: str) -> str:
    return f"“{text}”"


def _preview(text: str) -> str:
    return clip_text(" ".join(text.split()), HIL_DESCRIPTION_PREVIEW_CHARS)


def _humanise_key(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def _capitalise(text: str) -> str:
    return text[:1].upper() + text[1:]


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]
