"""Resolve a playbook step's ``$placeholders`` against the run that is happening.

Pure: given a value and a :class:`RunContext`, produce the value the tool is
actually called with. No I/O, no ``eval``, no dynamic code — the vocabulary is a
closed table matched by one scanner, so an argument a playbook author writes can
only ever become data.

The one asymmetry worth knowing: the current run is addressed by step id
(``$steps.<id>``) and the previous run by TOOL NAME (``$last_run.<TOOL>``),
because the run before a playbook's first replay was agentic and has no step ids
at all. That is also why a ``$last_run`` naming a tool the previous run never
called is ``None`` rather than an error: a first replay legitimately has nothing
to look back at. Every other miss — a ``$last_run`` path absent from what that
tool did return, an unresolvable ``$steps`` / ``$trigger`` / ``$user`` — means
the playbook no longer matches reality and must fail loudly instead of calling a
tool with a hole in it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import re
from typing import Any

from app.models.playbook_models import ASK_KEY, ask_slot_key, is_ask_slot
from app.models.workflow_execution_models import RECORD_CUT_MARKER, RecordedCall
from app.services.workflow.playbook.placeholders import PLACEHOLDER_TOKEN
from app.utils.errors import AppError

#: Offset suffixes ``$now``/``$today`` accept, as ``timedelta`` keywords.
_OFFSET_UNITS: dict[str, str] = {
    "w": "weeks",
    "d": "days",
    "h": "hours",
    "m": "minutes",
    "s": "seconds",
}

#: The only fields ``$user`` exposes.
_USER_FIELDS = ("email", "name", "timezone")

#: Addresses the file a step offloaded its result to, rather than the result.
#: Public because the validator has to exempt it: the offload file exists only
#: at replay, so checking it against the authoring run's result would refuse a
#: reference that is correct.
STEP_FILE_FIELD = "file"


@dataclass
class PlaceholderError(AppError):
    """A placeholder this run cannot resolve, named so the failure says which one.

    Raised for ``$steps`` / ``$trigger`` / ``$user``, and for an ask slot no
    model wrote: every one of them addresses something this run was supposed to
    have, so a miss means the playbook is stale and the run must stop rather
    than proceed with a gap.
    """


@dataclass(frozen=True, slots=True)
class PlaybookUser:
    """The user fields a playbook may address."""

    email: str
    name: str
    timezone: str


@dataclass(frozen=True, slots=True)
class StepResult:
    """What one executed step leaves behind for the steps after it.

    ``value`` is the tool's result parsed as JSON when it is JSON, and the raw
    string otherwise. ``file`` is the workspace path when the tool offloaded its
    result instead of returning it inline.
    """

    value: object
    file: str | None = None


@dataclass(frozen=True, slots=True)
class RunContext:
    """Everything a placeholder may be resolved against."""

    user: PlaybookUser
    #: Timezone-aware, in the workflow's own zone — ``$now``/``$today`` are the
    #: user's clock, not the worker's.
    now: datetime
    trigger: Mapping[str, object]
    #: Empty until steps run; defaulted so construction sites carry no dead
    #: placeholder arguments.
    steps: Mapping[str, StepResult] = field(default_factory=dict)
    #: Previous run's results keyed by TOOL NAME (see the module docstring).
    last_run: Mapping[str, object] = field(default_factory=dict)
    #: What the mid-run model call wrote, keyed the way ``ask_slot_key`` spells
    #: a slot's address. Read by ``fill_ask_slots``, never by ``resolve_value``.
    asks: Mapping[str, str] = field(default_factory=dict)


def last_run_index(trace: Sequence[RecordedCall]) -> dict[str, object]:
    """The previous run's results keyed by tool name, most recent call winning.

    A tool called several times in one run resolves to its LAST result, which is
    what a cursor placeholder (``$last_run.GMAIL_FETCH_MESSAGES.next_page``)
    wants: where the run finished, not where it started.
    """
    index: dict[str, object] = {}
    for call in trace:
        index[call.tool_name] = parse_result(call.result_digest)
    return index


def fill_ask_slots(
    args: Mapping[str, Any], asks: Mapping[str, str], key_prefix: str
) -> dict[str, Any]:
    """One step's arguments with every inline ask slot replaced by its written text.

    Pure, and deliberately a separate pass ahead of :func:`resolve_args`: a slot
    becomes an ordinary string first, and is then scanned for placeholders like
    any other value. That is what keeps ``$ask`` a value in the grammar rather
    than a second grammar with its own resolution rules.

    ``key_prefix`` is the step's id (its tool name when it has no id); together
    with the argument path it spells the key the ask call answered under.
    """
    return {
        str(key): _fill_value(value, asks, key_prefix, (str(key),)) for key, value in args.items()
    }


def _fill_value(
    value: object, asks: Mapping[str, str], prefix: str, path: tuple[str | int, ...]
) -> object:
    if is_ask_slot(value):
        key = ask_slot_key(prefix, path)
        if key not in asks:
            raise PlaceholderError(
                message=f"{key} was never written",
                why="the run's ask call produced no text for that slot",
                fix="write one entry per slot listed, keyed exactly as the slot is listed",
            )
        return asks[key]
    if isinstance(value, Mapping):
        return {
            str(key): _fill_value(item, asks, prefix, (*path, str(key)))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_fill_value(item, asks, prefix, (*path, index)) for index, item in enumerate(value)]
    return value


def resolve_args(args: Mapping[str, Any], context: RunContext) -> dict[str, Any]:
    """One step's arguments with every placeholder resolved.

    An argument that IS a placeholder and resolves to ``None`` (a ``$last_run``
    with no history behind it) is left out, so the tool's own default applies
    rather than a null reaching a parameter that does not accept one. A literal
    null, and a null inside a nested value, are kept as written.
    """
    resolved: dict[str, Any] = {}
    for key, value in args.items():
        item = resolve_value(value, context)
        if item is None and isinstance(value, str) and PLACEHOLDER_TOKEN.fullmatch(value):
            continue
        if _carries_cut_value(item):
            # A recorded string cut to fit the record (a page token, a long id)
            # is not the value; sending the stub would page from nowhere. The
            # stub is just as wrong nested in a list or a dict, or interpolated
            # into a longer string, so the whole argument is scanned.
            raise PlaceholderError(
                f"{key}: the recorded value was cut when it was stored and cannot be replayed"
            )
        resolved[key] = item
    return resolved


def _carries_cut_value(value: object) -> bool:
    """Whether a resolved argument holds a string that was cut when recorded.

    The marker is searched for rather than matched at the end, because a cut
    value interpolated into a longer string (``page=<cut>&limit=50``) carries the
    stub in the middle and is no more replayable there than on its own.
    """
    if isinstance(value, str):
        return RECORD_CUT_MARKER in value
    if isinstance(value, Mapping):
        return any(_carries_cut_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_carries_cut_value(item) for item in value)
    return False


def resolve_value(value: object, context: RunContext) -> object:
    """Resolve one value, descending into lists and mappings.

    A whole-value placeholder keeps the resolved value's real type (so
    ``max_results: $steps.x.count`` stays an int); a placeholder embedded in a
    larger string is interpolated into it.
    """
    if is_ask_slot(value):
        # fill_ask_slots runs first and leaves none behind, so reaching one here
        # means a step was resolved without being filled — the text a model was
        # supposed to write is missing, and the slot's dict must not be sent as
        # an argument in its place.
        raise PlaceholderError(
            message=f"an {ASK_KEY} slot was not filled before resolution",
            why="the run resolved this step's arguments without first filling its ask slots",
            fix="fill the step's ask slots before resolving its arguments",
        )
    if isinstance(value, Mapping):
        return {str(key): resolve_value(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_value(item, context) for item in value]
    if not isinstance(value, str) or "$" not in value:
        return value

    whole = PLACEHOLDER_TOKEN.fullmatch(value)
    if whole is not None:
        return _resolve_token(whole, context)
    return PLACEHOLDER_TOKEN.sub(lambda match: _render(_resolve_token(match, context)), value)


def _resolve_token(match: re.Match[str], context: RunContext) -> object:
    token = match.group(0)
    root = match.group("root")
    path = match.group("path").lstrip(".")
    sign = match.group("sign")

    if root in ("now", "today"):
        if path:
            raise PlaceholderError(
                message=f"{token} is not a placeholder: ${root} takes no fields",
                why=f"${root} resolves to a time, so it has nothing to address under it",
                fix=f"write ${root} on its own, optionally with an offset like ${root} + 1d",
            )
        return _resolve_time(root, sign, match.group("amount"), match.group("unit"), context.now)

    if sign is not None:
        raise PlaceholderError(
            message=f"{token} applies a time offset to ${root}",
            why="only $now and $today take an offset",
            fix=f"drop the offset from ${root}",
        )

    if root == "user":
        return _resolve_user(token, path, context.user)
    if root == "trigger":
        return _resolve_required(token, context.trigger, path, "the trigger payload")
    if root == "steps":
        return resolve_step(token, path, context.steps)
    return _resolve_last_run(token, path, context.last_run)


def _resolve_time(
    root: str, sign: str | None, amount: str | None, unit: str | None, now: datetime
) -> str:
    moment = now
    if unit is not None and amount is not None:
        offset = timedelta(**{_OFFSET_UNITS[unit]: int(amount)})
        moment = now - offset if sign == "-" else now + offset
    # Seconds, not microseconds: some APIs reject the longer form as not RFC 3339.
    return moment.date().isoformat() if root == "today" else moment.isoformat(timespec="seconds")


def _resolve_user(token: str, path: str, user: PlaybookUser) -> str:
    fields: dict[str, str] = {
        "email": user.email,
        "name": user.name,
        "timezone": user.timezone,
    }
    if path not in fields:
        raise PlaceholderError(
            message=f"{token} addresses no user field",
            why=f"$user exposes {', '.join(_USER_FIELDS)} and nothing else",
            fix="address one of those fields",
        )
    value = fields[path]
    if not value:
        raise PlaceholderError(
            message=f"{token} is empty for this user",
            why=f"the user profile carries no {path}",
            fix=f"set a {path} on the profile, or stop addressing it from the playbook",
        )
    return value


def resolve_step(token: str, path: str, steps: Mapping[str, StepResult]) -> object:
    """One ``$steps.<id>.<path>`` reference against the results in hand.

    Public because the validator resolves the same references against the run
    that is AUTHORING the playbook, using the results that run already has. Two
    path walkers would be two answers to "does this reference resolve", and the
    validator's would be the one that never runs in production.
    """
    step_id, _, rest = path.partition(".")
    result = steps.get(step_id)
    if result is None:
        raise PlaceholderError(
            message=f"{token} points at a step that has not run",
            why=f"no earlier step in this replay is named {step_id!r}",
            fix="reference a step that runs before this one, or rewrite the playbook",
        )
    if rest == STEP_FILE_FIELD and result.file is not None:
        return result.file
    return _resolve_required(token, result.value, rest, f"step {step_id!r}'s result")


def _resolve_last_run(token: str, path: str, last_run: Mapping[str, object]) -> object:
    """The previous run's value, or ``None`` when there is nothing to look back at.

    A tool the previous run never called is deliberately not an error: the run
    before a playbook's first replay was agentic, so a value the playbook expects
    to carry over may simply not exist yet — and the first replay must still run.
    A tool it DID call whose result lacks the path is: the playbook expects a
    shape the tool no longer returns (or the result was recorded as text), and
    calling the tool with ``None`` where a cursor belongs restarts from the top.
    """
    tool_name, _, rest = path.partition(".")
    if tool_name not in last_run:
        return None
    recorded = last_run[tool_name]
    value, found = _walk(recorded, rest)
    if found:
        return value
    raise PlaceholderError(
        message=f"{token} is not in what {tool_name} returned last run",
        why=(
            "that result was recorded as text, not JSON, so it has no fields to address"
            if isinstance(recorded, str)
            else "the previous run's result for that tool has no value at that path"
        ),
        fix="re-author the playbook against a run whose result has this shape",
    )


def _resolve_required(token: str, root: object, path: str, where: str) -> object:
    value, found = _walk(root, path)
    if not found:
        raise PlaceholderError(
            message=f"{token} is not in {where}",
            why="the value the playbook expects to read is absent from what actually came back",
            fix="re-author the playbook against a run that produced this shape",
        )
    return value


def _walk(root: object, path: str) -> tuple[object, bool]:
    """Follow a dotted path through mappings and lists. ``(value, found)``."""
    current = root
    if not path:
        return current, True
    for part in path.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return None, False
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None, False
    return current, True


def parse_result(digest: str) -> object:
    """A recorded result as JSON when it is JSON, and as its own text otherwise."""
    try:
        return json.loads(digest)
    except (ValueError, TypeError):
        return digest


def _render(value: object) -> str:
    """A resolved value as it reads inside a larger string.

    ``None`` renders as nothing rather than the word "None": it is either a
    ``$last_run`` with no history behind it or a recorded JSON null, and neither
    should reach a tool as the literal text.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, default=str)
