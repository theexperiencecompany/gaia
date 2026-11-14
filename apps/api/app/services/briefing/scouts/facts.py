"""Render today's signals, with their memory, as the facts block the brief's voice pass reads."""

from collections.abc import Sequence
from datetime import datetime
from itertools import groupby

from app.constants.scouts import SIGNAL_NEW_WITHIN
from app.models.scout_models import RememberedSignal, Signal, SignalImportance
from app.utils.timezone import as_utc

SIGNALS_HEADER = "[ACROSS THEIR APPS]"


def _days_ago(then: datetime, now: datetime) -> str:
    days = (now.date() - then.date()).days
    if days <= 0:
        return "today"
    return "yesterday" if days == 1 else f"{days} days ago"


def _first_sighting(signal: Signal, now: datetime) -> str:
    """Say how old an item no brief saw before is: new only when the app dates it inside the day."""
    created = as_utc(signal.created_at)
    if created is None:
        return "first seen today, created date unknown"
    if now - created < SIGNAL_NEW_WITHIN:
        return f"new: created {_days_ago(created, now)}"
    note = f"first seen today, created {created.date().isoformat()} ({_days_ago(created, now)})"
    updated = as_utc(signal.updated_at)
    if updated is not None:
        note += f", last updated {_days_ago(updated, now)}"
    return note


def memory_note(item: RememberedSignal, now: datetime) -> str:
    """Say what earlier briefs remember of an item: first seen, times mentioned, how it moved."""
    memory = item.memory
    if memory is None:
        return _first_sighting(item.signal, now)
    seen = f"first seen {_days_ago(memory.first_seen, now)}"
    if memory.times_shown and memory.last_shown is not None:
        seen += (
            f", mentioned {memory.times_shown} time(s), last {_days_ago(memory.last_shown, now)}"
        )
    else:
        seen += ", never mentioned"
    if item.previous_state is not None:
        seen += f", moved from {item.previous_state} to {item.signal.state}"
    return seen


def _line(fact_id: int, item: RememberedSignal, now: datetime) -> str:
    signal = item.signal
    parts = [
        f"- fact {fact_id} | {'important' if signal.importance is SignalImportance.HIGH else 'other'}"
        f" | {signal.kind}: {signal.title}"
    ]
    if signal.state:
        parts.append(f"state: {signal.state}")
    if signal.due_at is not None:
        parts.append(f"due {signal.due_at.date().isoformat()}")
    if signal.people:
        parts.append(f"with {', '.join(signal.people)}")
    if signal.url:
        parts.append("linkable")
    if signal.why:
        parts.append(f"why: {signal.why}")
    parts.append(memory_note(item, now))
    return " | ".join(parts)


def signals_block(remembered: Sequence[tuple[int, RememberedSignal]], now: datetime) -> str:
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
    lines = [f"{SIGNALS_HEADER} {len(remembered)} item(s) in {len(apps)} app(s)"]
    for app, items in groupby(ordered, key=lambda pair: pair[1].signal.app):
        group = list(items)
        lines.append(f"[{app}] {len(group)} item(s)")
        lines.extend(_line(fact_id, item, now) for fact_id, item in group)
    return "\n".join(lines)
