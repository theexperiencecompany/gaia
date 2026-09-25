"""Every model call one browser run makes: which component, which provider, how long, what it cost.

The runner meters the run's spend from it and the eval reads it; nothing here
decides anything.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum


class CallComponent(StrEnum):
    """Which part of the run made a model call."""

    JEV = "jev"
    TEXT = "text"
    AGENT = "agent"


@dataclass(frozen=True)
class ModelCall:
    component: CallComponent
    provider: str
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    #: What the provider reported the call cost; None when it reports nothing.
    cost_usd: float | None = None


@dataclass(frozen=True)
class ExecutedAction:
    """One browser action as executed, by whichever component chose it."""

    component: CallComponent
    description: str
    duration_ms: int
    #: The browser actions this entry stands for: one for Jev's, an agent step's own
    #: actions for the agent's (a step that hands Jev a goal counts none; Jev counts its).
    count: int = 1


@dataclass
class RunLedger:
    """The run's model calls and executed actions, in the order they finished."""

    #: Told of each call as it lands, so spend is metered while the run is still going.
    on_call: Callable[[ModelCall], None] | None = None
    calls: list[ModelCall] = field(default_factory=list)
    actions: list[ExecutedAction] = field(default_factory=list)

    def add(self, call: ModelCall) -> None:
        self.calls.append(call)
        if self.on_call is not None:
            self.on_call(call)

    def executed(self, action: ExecutedAction) -> None:
        self.actions.append(action)

    @property
    def action_count(self) -> int:
        """How many browser actions the run executed, Jev's and the agent's."""
        return sum(action.count for action in self.actions)
