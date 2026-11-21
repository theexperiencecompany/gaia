"""Read a scout's frozen results into signals, by the paths its learn run named.

One malformed item never costs the app its other items: an item missing a required
field (id, title) is skipped, and an optional field that cannot be read is left empty.
Only a result where no item reads at all, or whose items are not a list, means the
app's result no longer has the shape the scout learned; that raises PlaceholderError
and the caller relearns the scout. Every replayed signal starts normal: which matter,
and how much, is the judge's call.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

from pydantic import TypeAdapter, ValidationError

from app.constants.scouts import (
    API_HOST_LABEL,
    PERSON_ID_KEYS,
    PERSON_NAME_KEYS,
    SCOUT_SIGNAL_CEILING,
)
from app.models.scout_models import Signal, SignalSource
from app.services.briefing.scouts.tools import ScoutIntegration
from app.services.workflow.playbook.evaluator import (
    PlaceholderError,
    StepResult,
    resolve_item,
    resolve_step,
    walk_path,
)
from shared.py.wide_events import log

_DATETIME = TypeAdapter(datetime)


def _shape_error(what: str, value: object) -> PlaceholderError:
    return PlaceholderError(
        message=f"{what} is a {type(value).__name__}, not the value the scout learned",
        why="the app's result no longer has the shape the scout froze",
        fix="relearn the scout against the app's current results",
    )


def _text(value: object) -> str | None:
    """Return a scalar as non-empty text, or None when it is not one."""
    if isinstance(value, str | int | float) and not isinstance(value, bool):
        return str(value) or None
    return None


@dataclass
class _Item:
    """One item being read, and the optional fields it held that could not be read."""

    value: object
    unread: list[str] = field(default_factory=list)

    def required(self, token: str, path: str, what: str) -> str:
        raw = resolve_item(token, path, self.value)
        text = _text(raw)
        if text is None:
            raise _shape_error(what, raw)
        return text

    def optional(self, path: str | None) -> object:
        """Return an optional field's value; None when the item has no such field or it is empty."""
        if path is None:
            return None
        value, _found = walk_path(self.value, path)
        return None if value == "" else value

    def text(self, path: str | None, what: str) -> str | None:
        raw = self.optional(path)
        text = _text(raw)
        if raw is not None and text is None:
            self.unread.append(what)
        return text

    def page(self, path: str | None) -> str | None:
        """Return the item's link when a person can open it; an app's API endpoint reads as unread."""
        url = self.text(path, "url")
        page = page_url(url)
        if url is not None and page is None:
            self.unread.append("url")
        return page

    def moment(self, path: str | None, what: str) -> datetime | None:
        raw = self.optional(path)
        if raw is None:
            return None
        try:
            moment = _DATETIME.validate_python(raw)
        except ValidationError:
            self.unread.append(what)
            return None
        return moment if moment.tzinfo else moment.replace(tzinfo=UTC)

    def amount(self, path: str | None) -> float | None:
        """Return a figure as a number; a numeric string reads as its number."""
        raw = self.optional(path)
        if raw is None:
            return None
        if isinstance(raw, int | float) and not isinstance(raw, bool):
            return float(raw)
        if isinstance(raw, str):
            try:
                return float(raw)
            except ValueError:
                pass
        self.unread.append("amount")
        return None

    def state(self, path: str | None) -> str | None:
        """Return a status as text; a flag reads as its field and value, e.g. checked: false."""
        raw = self.optional(path)
        if path is not None and isinstance(raw, bool):
            return f"{path.split('.')[-1]}: {'true' if raw else 'false'}"
        return self.text(path, "state")

    def people(self, path: str | None, handles: frozenset[str]) -> tuple[list[str], list[str]]:
        """Return each person's name, and the names of those who are the user by their handles."""
        raw = self.optional(path)
        if raw is None:
            return [], []
        named = [(person, _person(person)) for person in (raw if isinstance(raw, list) else [raw])]
        if any(name is None for _, name in named):
            self.unread.append("people")
        people = [name for _, name in named if name is not None]
        you = [name for person, name in named if name is not None and is_the_user(person, handles)]
        return people, you


def page_url(url: str | None) -> str | None:
    """Return url when a person can open it as a page; None for an app's API endpoint."""
    if url is None or urlsplit(url).netloc.split(".")[0] == API_HOST_LABEL:
        return None
    return url


def is_the_user(person: object, handles: frozenset[str]) -> bool:
    """Say whether an app's person, a handle or an object, carries one of the user's own handles.

    An object is matched on its identity fields only: a display name is free text any
    teammate can set to the user's handle.
    """
    if isinstance(person, Mapping):
        return any(
            isinstance(value, str) and value.casefold() in handles
            for value in (person.get(key) for key in PERSON_ID_KEYS)
        )
    return isinstance(person, str) and person.casefold() in handles


def _person(value: object) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, Mapping):
        for key in PERSON_NAME_KEYS:
            name = value.get(key)
            if isinstance(name, str) and name:
                return name
    return None


def _signal(integration: ScoutIntegration, source: SignalSource, item: _Item) -> Signal:
    fields = source.fields
    token = f"$steps.{source.step_id}"
    amount = item.amount(fields.amount)
    people, you = item.people(fields.people, integration.handles)
    return Signal(
        integration_id=integration.integration_id,
        app=integration.name,
        external_id=item.required(token, fields.external_id, "external_id"),
        kind=source.kind,
        title=item.required(token, fields.title, "title"),
        due_at=item.moment(fields.due_at, "due_at"),
        people=people,
        people_role=fields.people_role,
        people_you=you,
        url=item.page(fields.url),
        state=item.state(fields.state),
        amount=amount,
        amount_unit=source.amount_unit if amount is not None else None,
        text=item.text(fields.text, "text"),
        author=_person(item.optional(fields.author)),
        created_at=item.moment(fields.created_at, "created_at"),
        updated_at=item.moment(fields.updated_at, "updated_at"),
    )


def _source_signals(
    integration: ScoutIntegration, source: SignalSource, items: list[object]
) -> list[Signal]:
    """Read every item that has its required fields; raise when items exist but none reads."""
    signals: list[Signal] = []
    skipped: list[PlaceholderError] = []
    degraded: set[str] = set()
    for value in items:
        item = _Item(value)
        try:
            signals.append(_signal(integration, source, item))
        except PlaceholderError as exc:
            skipped.append(exc)
            continue
        degraded.update(item.unread)
    if skipped and not signals:
        raise skipped[0]
    if skipped or degraded:
        log.warning(
            "briefing.scout_items_unread",
            integration_id=integration.integration_id,
            step_id=source.step_id,
            items=len(items),
            skipped=len(skipped),
            skip_reason=skipped[0].message if skipped else None,
            unread_fields=sorted(degraded),
        )
    return signals


def extract_signals(
    integration: ScoutIntegration, sources: Sequence[SignalSource], values: Mapping[str, object]
) -> list[Signal]:
    """Return every readable item the sources point at as a signal, up to the safety ceiling."""
    steps = {step_id: StepResult(value=value) for step_id, value in values.items()}
    signals: list[Signal] = []
    for source in sources:
        path = f"{source.step_id}.{source.items_path}" if source.items_path else source.step_id
        items = resolve_step(f"$steps.{path}", path, steps)
        if not isinstance(items, list):
            raise _shape_error(f"{source.step_id}'s items", items)
        signals.extend(_source_signals(integration, source, items))
    return signals[:SCOUT_SIGNAL_CEILING]
