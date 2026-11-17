"""Per-turn stage stamps: how much of a reply's latency is ours, not the provider's.

received -ingress- t0 -prep- llm_request -provider- llm_first_chunk -egress- frame_written

The provider stretch is the model's own time to first token; the other three are
ours and sum to the turn's overhead. The clock lives on the turn's StreamSession so
the request handler, the LLM callback and the SSE reader stamp the same object.
"""

from dataclasses import dataclass, field
from enum import StrEnum
import time

from starlette.requests import Request

from app.services.turn_timings import (
    TurnPhase,
    TurnTimings,
    begin_turn_timings,
    current_turn_timings,
)

#: request.state attribute LoggingMiddleware stamps on arrival.
_RECEIVED_STATE_ATTR = "turn_received_perf"


class TurnMark(StrEnum):
    """The stamps a turn collects after it is received."""

    T0 = "t0"
    LLM_REQUEST = "llm_request"
    LLM_FIRST_CHUNK = "llm_first_chunk"
    FRAME_WRITTEN = "frame_written"


#: The step-timing phase a turn enters at each stamp.
_PHASE_AFTER: dict[TurnMark, TurnPhase] = {
    TurnMark.T0: TurnPhase.PREP,
    TurnMark.LLM_REQUEST: TurnPhase.CLOSED,
}


class TurnPath(StrEnum):
    """Which shape of turn produced the first visible text."""

    #: The first comms model call wrote it — the path the overhead budget covers.
    DIRECT = "direct"
    #: A tool round-trip ran first, so the provider stretch covers only the first call.
    TOOL_LOOP = "tool_loop"
    #: The turn handed work to the executor.
    DELEGATED = "delegated"


@dataclass(frozen=True)
class TurnOverhead:
    """One turn's stretches in seconds; total is ingress + prep + egress."""

    ingress: float
    prep: float
    provider_ttft: float
    egress: float
    path: TurnPath

    @property
    def total(self) -> float:
        return self.ingress + self.prep + self.egress


def stamp_received(request: Request) -> None:
    """Record when the request reached the outermost HTTP middleware, and begin its step timings."""
    setattr(request.state, _RECEIVED_STATE_ATTR, time.perf_counter())
    begin_turn_timings()


@dataclass
class TurnClock:
    """perf_counter stamps for one turn; each mark keeps its first write.

    received is None when the request never crossed LoggingMiddleware (a direct
    handler call): such a turn reports no overhead rather than a wrong ingress.
    """

    received: float | None
    marks: dict[TurnMark, float] = field(default_factory=dict)
    delegated: bool = False
    #: Comms model calls that started before the first frame reached the client.
    comms_calls_before_text: int = 0
    #: The request's step timings; t0 moves them to prep, the first model request closes them.
    timings: TurnTimings | None = None

    @classmethod
    def accepted(cls, request: Request) -> "TurnClock":
        """Start the clock for a turn the endpoint just accepted, stamping t0 now."""
        clock = cls(
            received=getattr(request.state, _RECEIVED_STATE_ATTR, None),
            timings=current_turn_timings(),
        )
        clock.mark(TurnMark.T0)
        return clock

    def mark(self, name: TurnMark) -> None:
        self.marks.setdefault(name, time.perf_counter())
        if self.timings is not None and (phase := _PHASE_AFTER.get(name)) is not None:
            self.timings.enter(phase)

    def note_comms_call(self) -> None:
        if TurnMark.FRAME_WRITTEN not in self.marks:
            self.comms_calls_before_text += 1

    def _path(self) -> TurnPath:
        if self.delegated:
            return TurnPath.DELEGATED
        return TurnPath.TOOL_LOOP if self.comms_calls_before_text > 1 else TurnPath.DIRECT

    def missing(self) -> list[str]:
        """Return the stamps not yet taken, in turn order (received first)."""
        absent = ["received"] if self.received is None else []
        return absent + [mark.value for mark in TurnMark if mark not in self.marks]

    def overhead(self) -> TurnOverhead | None:
        """Return the turn's stretches, or None until every mark is in."""
        received = self.received
        if received is None or self.missing():
            return None
        m = self.marks
        return TurnOverhead(
            ingress=m[TurnMark.T0] - received,
            prep=m[TurnMark.LLM_REQUEST] - m[TurnMark.T0],
            provider_ttft=m[TurnMark.LLM_FIRST_CHUNK] - m[TurnMark.LLM_REQUEST],
            egress=m[TurnMark.FRAME_WRITTEN] - m[TurnMark.LLM_FIRST_CHUNK],
            path=self._path(),
        )
