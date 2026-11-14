"""Integration trigger events: what GAIA decided about an event before it cost a run."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent
from shared.py.analytics.catalog.properties import Identifier

__all__ = ["TriggerGateDecided", "TriggerGateEdited"]


class TriggerGateDecided(ServerEvent):
    """A trigger gate decided what a fired event does to its workflow or tracked todo.

    outcome is what the run did and reason is why, so a shadow gate (enforced
    false) reports reason jev_skip with outcome run. Inside the user's quiet hours
    an event is held for the morning or let through now; urgent_choice names why
    a let-through one could not wait.
    """

    event: ClassVar[str] = "trigger:gate_decided"
    # One per gated event: a busy inbox fires a Gmail gate a few hundred times a day.
    budget_per_user_day: ClassVar[int] = 500

    owner_type: Literal["workflow", "todo"]
    trigger_name: Identifier
    gate_kind: Literal["authored", "system"]
    author: Literal["gaia", "user"] | None = None
    outcome: Literal["run", "skip", "hold", "bypass"]
    reason: Literal[
        "jev_run",
        "jev_skip",
        "jev_urgent",
        "jev_can_wait",
        "free_run",
        "jev_error",
        "jev_timeout",
        "jev_malformed",
        "jev_unconfigured",
    ]
    urgent_choice: Literal["incident", "service_down", "meeting", "can_wait"] | None = None
    enforced: bool
    latency_ms: int | None = None


class TriggerGateEdited(ServerEvent):
    """A user added, rewrote, turned on or off, or removed the gate on a workflow or tracked todo."""

    event: ClassVar[str] = "trigger:gate_edited"
    budget_per_user_day: ClassVar[int] = 20

    owner_type: Literal["workflow", "todo"]
    action: Literal["added", "edited", "disabled", "enabled", "removed"]
    gate_kind: Literal["authored", "system"]
