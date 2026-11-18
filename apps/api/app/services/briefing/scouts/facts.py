"""Render today's signals, with their memory, as the facts block the brief's voice pass reads."""

from collections.abc import Sequence
from datetime import datetime
from itertools import groupby

from app.constants.scouts import SIGNAL_NEW_WITHIN
from app.models.scout_models import (
    PeopleRole,
    RememberedSignal,
    Signal,
    SignalImportance,
    SignalMemoryDocument,
)
from app.services.briefing.clock import UserClock
from app.utils.timezone import as_utc

SIGNALS_HEADER = "[ACROSS THEIR APPS]"
#: A scout reads one page of an app, capped at SCOUT_SIGNAL_CEILING, and the judge keeps
#: only what matters: a count here is what the brief shows, never how many the app holds.
SHOWN_NOT_TOTAL = "Counts are of the items shown here, not each app's total: an app may hold more."


#: Marks the one person on an item who is the user: never a third person to them.
YOU_MARK = "(this is the user: say you, never their name)"


def people_note(people: Sequence[str], role: PeopleRole | None, you: Sequence[str] = ()) -> str:
    """Say who an item names, which of them is the user, and what they are to it, when the app says."""
    names = ", ".join(f"{name} {YOU_MARK}" if name in you else name for name in people)
    if role is None:
        return f"names {names} (the app does not say their part in it)"
    return f"{role.value}: {names}"


def _days_ago(then: datetime, clock: UserClock) -> str:
    """Say how many of the user's own days ago a moment was."""
    days = (clock.now_local.date() - clock.day_of(then)).days
    if days <= 0:
        return "today"
    return "yesterday" if days == 1 else f"{days} days ago"


def _first_sighting(signal: Signal, clock: UserClock) -> str:
    """Say how old an item no brief saw before is: new only when the app dates it inside the day."""
    created = as_utc(signal.created_at)
    if created is None:
        return "first seen today, created date unknown"
    if clock.now_local - created < SIGNAL_NEW_WITHIN:
        return f"new: created {_days_ago(created, clock)}"
    note = f"first seen today, created {clock.day_of(created).isoformat()} ({_days_ago(created, clock)})"
    updated = as_utc(signal.updated_at)
    if updated is not None:
        note += f", last updated {_days_ago(updated, clock)}"
    return note


def seen_note(memory: SignalMemoryDocument, clock: UserClock) -> str:
    """Say what earlier briefs remember of an item: when it was first seen and how often it was shown."""
    seen = f"first seen {_days_ago(memory.first_seen, clock)}"
    if memory.times_shown and memory.last_shown is not None:
        return seen + (
            f", mentioned {memory.times_shown} time(s), last {_days_ago(memory.last_shown, clock)}"
        )
    return seen + ", never mentioned"


def memory_note(item: RememberedSignal, clock: UserClock) -> str:
    """Say what earlier briefs remember of a signal: first seen, times mentioned, how it moved."""
    if item.memory is None:
        return _first_sighting(item.signal, clock)
    seen = seen_note(item.memory, clock)
    if item.previous_state is not None:
        seen += f", moved from {item.previous_state} to {item.signal.state}"
    return seen


def _line(fact_id: int, item: RememberedSignal, clock: UserClock) -> str:
    signal = item.signal
    parts = [
        f"- fact {fact_id} | {'important' if signal.importance is SignalImportance.HIGH else 'other'}"
        f" | {signal.kind}: {signal.title}"
    ]
    if signal.state:
        parts.append(f"state: {signal.state}")
    if signal.due_at is not None:
        parts.append(f"due {clock.day_of(signal.due_at).isoformat()}")
    if signal.people:
        parts.append(people_note(signal.people, signal.people_role, signal.people_you))
    if signal.url:
        parts.append("linkable")
    if signal.why:
        parts.append(f"why: {signal.why}")
    parts.append(memory_note(item, clock))
    return " | ".join(parts)


def signals_block(remembered: Sequence[tuple[int, RememberedSignal]], clock: UserClock) -> str:
    """Group signals, each by its fact id, per app, important ones first; empty when there are none."""
    if not remembered:
        return ""
    ordered = sorted(
        remembered,
        key=lambda pair: (
            pair[1].signal.app,
            pair[1].signal.importance is not SignalImportance.HIGH,
        ),
    )
    apps = {r.signal.integration_id for _, r in remembered}
    lines = [
        f"{SIGNALS_HEADER} {len(remembered)} item(s) shown from {len(apps)} app(s). "
        f"{SHOWN_NOT_TOTAL}"
    ]
    for app, items in groupby(ordered, key=lambda pair: pair[1].signal.app):
        group = list(items)
        lines.append(f"[{app}] {len(group)} item(s) shown")
        lines.extend(_line(fact_id, item, clock) for fact_id, item in group)
    return "\n".join(lines)
