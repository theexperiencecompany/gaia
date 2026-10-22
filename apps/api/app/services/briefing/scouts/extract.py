"""Read a scout's frozen results into signals, by the paths its learn run named.

Required fields (id, title) missing from an item mean the app's result no longer has the
shape the scout learned, which raises PlaceholderError; the caller relearns that scout.
Every replayed signal starts normal: which matter, and how much, is the judge's call.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from pydantic import TypeAdapter, ValidationError

from app.constants.scouts import PERSON_NAME_KEYS, SCOUT_SIGNAL_CEILING
from app.models.scout_models import Signal, SignalSource
from app.services.briefing.scouts.tools import ScoutIntegration
from app.services.workflow.playbook.evaluator import (
    PlaceholderError,
    StepResult,
    resolve_item,
    resolve_step,
    walk_path,
)

_DATETIME = TypeAdapter(datetime)


def _shape_error(what: str, value: object) -> PlaceholderError:
    return PlaceholderError(
        message=f"{what} is a {type(value).__name__}, not the value the scout learned",
        why="the app's result no longer has the shape the scout froze",
        fix="relearn the scout against the app's current results",
    )


def _as_text(value: object, what: str) -> str:
    if isinstance(value, str | int | float) and not isinstance(value, bool):
        return str(value)
    raise _shape_error(what, value)


def _optional(item: object, path: str | None) -> object:
    """Return the value at an optional field's path, or None when the item has no such field."""
    if path is None:
        return None
    value, _found = walk_path(item, path)
    return value


def _due(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        moment = _DATETIME.validate_python(value)
    except ValidationError as exc:
        raise _shape_error("due_at", value) from exc
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _state(value: object, path: str) -> str:
    """Return a status as text; a flag reads as its field and value, e.g. checked: false."""
    if isinstance(value, bool):
        field = path.split(".")[-1]
        return f"{field}: {'true' if value else 'false'}"
    return _as_text(value, "state")


def _person(value: object) -> str:
    """Return one person's name: the value itself, or an object's first name-like field."""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        for key in PERSON_NAME_KEYS:
            name = value.get(key)
            if isinstance(name, str) and name:
                return name
    raise _shape_error("a person in people", value)


def _people(value: object) -> list[str]:
    if value is None:
        return []
    people = value if isinstance(value, list) else [value]
    return [_person(person) for person in people]


def _signal(integration: ScoutIntegration, source: SignalSource, item: object) -> Signal:
    fields = source.fields
    token = f"$steps.{source.step_id}"
    url, state = _optional(item, fields.url), _optional(item, fields.state)
    return Signal(
        integration_id=integration.integration_id,
        app=integration.name,
        external_id=_as_text(resolve_item(token, fields.external_id, item), "external_id"),
        kind=source.kind,
        title=_as_text(resolve_item(token, fields.title, item), "title"),
        due_at=_due(_optional(item, fields.due_at)),
        people=_people(_optional(item, fields.people)),
        url=None if url is None else _as_text(url, "url"),
        state=None if state is None or fields.state is None else _state(state, fields.state),
    )


def extract_signals(
    integration: ScoutIntegration, sources: Sequence[SignalSource], values: Mapping[str, object]
) -> list[Signal]:
    """Return every item the sources point at as a signal, up to the safety ceiling."""
    steps = {step_id: StepResult(value=value) for step_id, value in values.items()}
    signals: list[Signal] = []
    for source in sources:
        path = f"{source.step_id}.{source.items_path}" if source.items_path else source.step_id
        items = resolve_step(f"$steps.{path}", path, steps)
        if not isinstance(items, list):
            raise _shape_error(f"{source.step_id}'s items", items)
        signals.extend(_signal(integration, source, item) for item in items)
    return signals[:SCOUT_SIGNAL_CEILING]
