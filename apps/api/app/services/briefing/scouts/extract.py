"""Read a scout's frozen results into signals, by the paths its learn run named.

Required fields (id, title) missing from an item mean the app's result no longer has the
shape the scout learned, which raises PlaceholderError; the caller relearns that scout.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from pydantic import TypeAdapter, ValidationError

from app.constants.scouts import SCOUT_SIGNAL_CEILING, SIGNAL_URGENT_WINDOW
from app.models.scout_models import Signal, SignalImportance, SignalSource
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


def _people(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(person, str) for person in value):
        return list(value)
    raise _shape_error("people", value)


def _signal(
    integration: ScoutIntegration, source: SignalSource, item: object, now: datetime
) -> Signal:
    fields = source.fields
    token = f"$steps.{source.step_id}"
    due_at = _due(_optional(item, fields.due_at))
    url, state = _optional(item, fields.url), _optional(item, fields.state)
    return Signal(
        integration_id=integration.integration_id,
        app=integration.name,
        external_id=_as_text(resolve_item(token, fields.external_id, item), "external_id"),
        kind=source.kind,
        title=_as_text(resolve_item(token, fields.title, item), "title"),
        importance=(
            SignalImportance.HIGH
            if due_at is not None and due_at <= now + SIGNAL_URGENT_WINDOW
            else SignalImportance.NORMAL
        ),
        due_at=due_at,
        people=_people(_optional(item, fields.people)),
        url=None if url is None else _as_text(url, "url"),
        state=None if state is None else _as_text(state, "state"),
    )


def extract_signals(
    integration: ScoutIntegration,
    sources: Sequence[SignalSource],
    values: Mapping[str, object],
    now: datetime,
) -> list[Signal]:
    """Return every item the sources point at as a signal, up to the safety ceiling."""
    steps = {step_id: StepResult(value=value) for step_id, value in values.items()}
    signals: list[Signal] = []
    for source in sources:
        path = f"{source.step_id}.{source.items_path}" if source.items_path else source.step_id
        items = resolve_step(f"$steps.{path}", path, steps)
        if not isinstance(items, list):
            raise _shape_error(f"{source.step_id}'s items", items)
        signals.extend(_signal(integration, source, item, now) for item in items)
    return signals[:SCOUT_SIGNAL_CEILING]
