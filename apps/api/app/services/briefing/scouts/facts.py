"""Render today's signals, with their memory, as the facts block the brief's voice pass reads."""

from collections.abc import Sequence
from datetime import datetime
from itertools import groupby

from app.models.scout_models import RememberedSignal, SignalImportance

SIGNALS_HEADER = "[ACROSS THEIR APPS]"


def _days_ago(then: datetime, now: datetime) -> str:
    days = (now.date() - then.date()).days
    if days <= 0:
        return "today"
    return "yesterday" if days == 1 else f"{days} days ago"


def _memory_note(item: RememberedSignal, now: datetime) -> str:
    memory = item.memory
    if memory is None:
        return "new today"
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


def _line(item: RememberedSignal, now: datetime) -> str:
    signal = item.signal
    parts = [
        f"- {'important' if signal.importance is SignalImportance.HIGH else 'other'} | "
        f"{signal.kind}: {signal.title}"
    ]
    if signal.state:
        parts.append(f"state: {signal.state}")
    if signal.due_at is not None:
        parts.append(f"due {signal.due_at.date().isoformat()}")
    if signal.people:
        parts.append(f"with {', '.join(signal.people)}")
    if signal.url:
        parts.append(f"link: {signal.url}")
    if signal.why:
        parts.append(f"why: {signal.why}")
    parts.append(_memory_note(item, now))
    return " | ".join(parts)


def signals_block(remembered: Sequence[RememberedSignal], now: datetime) -> str:
    """Group signals per app, important ones first; empty when no scout found anything."""
    if not remembered:
        return ""
    ordered = sorted(
        remembered,
        key=lambda r: (r.signal.app, r.signal.importance is not SignalImportance.HIGH),
    )
    apps = {r.signal.integration_id for r in remembered}
    lines = [f"{SIGNALS_HEADER} {len(remembered)} item(s) in {len(apps)} app(s)"]
    for app, items in groupby(ordered, key=lambda r: r.signal.app):
        group = list(items)
        lines.append(f"[{app}] {len(group)} item(s)")
        lines.extend(_line(item, now) for item in group)
    return "\n".join(lines)
