"""Say what a signal names and what earlier briefs remember of it, as an item's line carries it."""

from collections.abc import Sequence
from datetime import datetime

from app.constants.scouts import SIGNAL_NEW_WITHIN
from app.models.scout_models import (
    PeopleRole,
    RememberedSignal,
    Signal,
    SignalMemoryDocument,
)
from app.services.briefing.clock import UserClock
from app.utils.timezone import as_utc

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


def _created(signal: Signal, clock: UserClock) -> str | None:
    """Say when the app dates an item's creation and last update; None when it does not."""
    created = as_utc(signal.created_at)
    if created is None:
        return None
    note = f"created {clock.day_of(created).isoformat()} ({_days_ago(created, clock)})"
    updated = as_utc(signal.updated_at)
    if updated is not None:
        note += f", last updated {_days_ago(updated, clock)}"
    return note


def _first_sighting(signal: Signal, clock: UserClock) -> str:
    """Say how old an item no brief saw before is: new only when the app dates it inside the day."""
    created = as_utc(signal.created_at)
    if created is not None and clock.now_local - created < SIGNAL_NEW_WITHIN:
        return f"new: created {_days_ago(created, clock)}"
    return f"first seen today, {_created(signal, clock) or 'created date unknown'}"


def seen_note(memory: SignalMemoryDocument, clock: UserClock) -> str:
    """Say what earlier briefs remember of an item: when it was first seen and how often it was shown."""
    seen = f"first seen {_days_ago(memory.first_seen, clock)}"
    if memory.times_shown and memory.last_shown is not None:
        return seen + (
            f", mentioned {memory.times_shown} time(s), last {_days_ago(memory.last_shown, clock)}"
        )
    return seen + ", never mentioned"


def memory_note(item: RememberedSignal, clock: UserClock) -> str:
    """Say what earlier briefs remember of a signal: first seen, times mentioned, its age, how it moved."""
    if item.memory is None:
        return _first_sighting(item.signal, clock)
    seen = seen_note(item.memory, clock)
    created = _created(item.signal, clock)
    if created is not None:
        seen += f", {created}"
    if item.previous_state is not None:
        seen += f", moved from {item.previous_state} to {item.signal.state}"
    return seen
