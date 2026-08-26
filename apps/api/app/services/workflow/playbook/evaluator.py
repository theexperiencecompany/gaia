"""Resolve a playbook step's ``$placeholders`` against the run that is happening.

Pure: given a value and a :class:`RunContext`, produce the value the tool is
actually called with. No I/O, no ``eval``, no dynamic code — the vocabulary is a
closed table matched by one scanner, so an argument a playbook author writes can
only ever become data.

The one asymmetry worth knowing: the current run is addressed by step id
(``$steps.<id>``) and the previous run by TOOL NAME (``$last_run.<TOOL>``),
because the run before a playbook's first replay was agentic and has no step ids
at all. That is also why an unresolvable ``$last_run`` is ``None`` rather than an
error: a first replay legitimately has nothing to look back at, while an
unresolvable ``$steps`` / ``$trigger`` / ``$user`` means the playbook no longer
matches reality and must fail loudly instead of calling a tool with a hole in it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import re
from typing import Any

from app.models.workflow_execution_models import RecordedCall
from app.services.workflow.playbook.parser import PLACEHOLDER_ROOTS
from app.utils.errors import AppError

#: Offset suffixes ``$now``/``$today`` accept, as ``timedelta`` keywords.
_OFFSET_UNITS: dict[str, str] = {
    "w": "weeks",
    "d": "days",
    "h": "hours",
    "m": "minutes",
    "s": "seconds",
}

#: Longest root first so ``last_run`` is never matched as a shorter alternative.
_ROOT_ALTERNATION = "|".join(sorted(PLACEHOLDER_ROOTS, key=len, reverse=True))

#: One token: a root from the parser's closed namespace set, an optional dotted
#: path, and (for the two time roots) an optional signed offset. Used to match,
#: never to build code — the match groups are read as data.
_TOKEN = re.compile(
    rf"\$(?P<root>{_ROOT_ALTERNATION})"
    r"(?P<path>(?:\.[A-Za-z0-9_-]+)*)"
    r"(?:\s*(?P<sign>[+-])\s*(?P<amount>\d+)(?P<unit>[wdhms])\b)?"
)

#: The only fields ``$user`` exposes.
_USER_FIELDS = ("email", "name", "timezone")

#: Addresses the file a step offloaded its result to, rather than the result.
_FILE_FIELD = "file"


@dataclass
class PlaceholderError(AppError):
    """A placeholder this run cannot resolve, named so the failure says which one.

    Raised for ``$steps`` / ``$trigger`` / ``$user`` / ``$ask``: every one of
    them addresses something this run was supposed to have, so a miss means the
    playbook is stale and the run must stop rather than proceed with a gap.
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
    steps: Mapping[str, StepResult]
    #: Previous run's results keyed by TOOL NAME (see the module docstring).
    last_run: Mapping[str, object]
    asks: Mapping[str, str]


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


def resolve_args(args: Mapping[str, Any], context: RunContext) -> dict[str, Any]:
    """One step's arguments with every placeholder resolved."""
    return {key: resolve_value(value, context) for key, value in args.items()}


def resolve_value(value: object, context: RunContext) -> object:
    """Resolve one value, descending into lists and mappings.

    A whole-value placeholder keeps the resolved value's real type (so
    ``max_results: $steps.x.count`` stays an int); a placeholder embedded in a
    larger string is interpolated into it.
    """
    if isinstance(value, Mapping):
        return {str(key): resolve_value(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_value(item, context) for item in value]
    if not isinstance(value, str) or "$" not in value:
        return value

    whole = _TOKEN.fullmatch(value)
    if whole is not None:
        return _resolve_token(whole, context)
    return _TOKEN.sub(lambda match: _render(_resolve_token(match, context)), value)


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
    if root == "ask":
        return _resolve_ask(token, path, context.asks)
    if root == "trigger":
        return _resolve_required(token, context.trigger, path, "the trigger payload")
    if root == "steps":
        return _resolve_step(token, path, context.steps)
    return _resolve_last_run(path, context.last_run)


def _resolve_time(
    root: str, sign: str | None, amount: str | None, unit: str | None, now: datetime
) -> str:
    moment = now
    if unit is not None and amount is not None:
        offset = timedelta(**{_OFFSET_UNITS[unit]: int(amount)})
        moment = now - offset if sign == "-" else now + offset
    return moment.date().isoformat() if root == "today" else moment.isoformat()


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


def _resolve_ask(token: str, path: str, asks: Mapping[str, str]) -> str:
    if path in asks:
        return asks[path]
    raise PlaceholderError(
        message=f"{token} was never written",
        why="the run's one model call produced no text for that ask",
        fix="declare the ask in the playbook, or stop addressing it",
    )


def _resolve_step(token: str, path: str, steps: Mapping[str, StepResult]) -> object:
    step_id, _, rest = path.partition(".")
    result = steps.get(step_id)
    if result is None:
        raise PlaceholderError(
            message=f"{token} points at a step that has not run",
            why=f"no earlier step in this replay is named {step_id!r}",
            fix="reference a step that runs before this one, or rewrite the playbook",
        )
    if rest == _FILE_FIELD and result.file is not None:
        return result.file
    return _resolve_required(token, result.value, rest, f"step {step_id!r}'s result")


def _resolve_last_run(path: str, last_run: Mapping[str, object]) -> object:
    """The previous run's value, or ``None`` when there is nothing to look back at.

    Deliberately not an error. The run before a playbook's first replay was
    agentic, so a value the playbook expects to carry over may simply not exist
    yet — and the first replay must still run.
    """
    tool_name, _, rest = path.partition(".")
    if tool_name not in last_run:
        return None
    value, found = _walk(last_run[tool_name], rest)
    return value if found else None


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

    ``None`` renders as nothing rather than the word "None": the only value that
    can be ``None`` here is an unresolved ``$last_run``, and a run with no
    history should send an empty cursor, not the literal text.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, default=str)
