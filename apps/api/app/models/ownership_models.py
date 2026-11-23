"""What comms hands the executor about the outcome a request is for."""

from dataclasses import dataclass, field

from app.constants.agents import TimeHorizon


@dataclass(frozen=True)
class ExecutorIntent:
    """The structured half of an executor brief: the real goal and how far it reaches."""

    desired_outcome: str
    time_horizon: TimeHorizon
    defaults_assumed: tuple[str, ...] = field(default_factory=tuple)
    irreversible_approved: bool = False
