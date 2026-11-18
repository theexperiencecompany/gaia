"""Where a chat turn's ingress goes: named steps and store round trips.

LoggingMiddleware begins a TurnTimings for each request and holds it in a
contextvar, so the middleware and the endpoint record into the same object. The
turn's accept closes it: ingress runs from arrival until the user's message is
in the conversation's log, and nothing is attributed after that.

Store clients report each round trip through record_store_call. A call lands on
the step active in the calling task, or on its phase's OTHER when none is, and
the time a phase spends outside every named step is reported as OTHER too, so
the named steps plus OTHER always add up to the phase.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
import time


class TurnPhase(StrEnum):
    """The stretches a step or store call is attributed to."""

    INGRESS = "ingress"
    #: Past the turn's accept: nothing more is attributed.
    CLOSED = "closed"


class TurnStep(StrEnum):
    """Named steps of ingress, in the order a turn usually meets them."""

    AUTH = "auth"
    BOT_AUTH = "bot_auth"
    ENTITLEMENT = "entitlement"
    RATE_LIMIT = "rate_limit"
    RESOLVE_USER = "resolve_user"
    PAYWALL = "paywall"
    CHARGE = "charge"
    SESSION = "session"
    #: Appending the user's message to the conversation's log.
    ACCEPT = "accept"
    #: Store calls from work a step spawned that outlived it: competing load, not waited on.
    BACKGROUND = "background"
    #: The phase's time and store calls no named step covers.
    OTHER = "other"


class Store(StrEnum):
    """Backing stores whose round trips a turn counts."""

    MONGO = "mongo"
    REDIS = "redis"
    POSTGRES = "postgres"


@dataclass
class StoreTally:
    """Round trips to one store and their summed wall time."""

    calls: int = 0
    seconds: float = 0.0


@dataclass
class StepReport:
    """One step of one phase: its time and the store round trips made inside it."""

    seconds: float
    stores: dict[Store, StoreTally]


@dataclass
class TurnTimings:
    """Step times and store tallies for one turn, keyed by the phase they ran in."""

    #: perf_counter when the request arrived; None for timings no request began.
    started: float | None = None
    phase: TurnPhase = TurnPhase.INGRESS
    steps: dict[tuple[TurnPhase, TurnStep], float] = field(default_factory=dict)
    stores: dict[tuple[TurnPhase, TurnStep, Store], StoreTally] = field(default_factory=dict)

    def enter(self, phase: TurnPhase) -> None:
        """Move to phase; phases only advance, so a late stamp cannot reopen one."""
        order = (TurnPhase.INGRESS, TurnPhase.CLOSED)
        if order.index(phase) > order.index(self.phase):
            self.phase = phase

    def add_step(self, phase: TurnPhase, step: TurnStep, seconds: float) -> None:
        if phase is TurnPhase.CLOSED:
            return
        key = (phase, step)
        self.steps[key] = self.steps.get(key, 0.0) + seconds

    def add_store_call(self, step: TurnStep, store: Store, seconds: float) -> None:
        if self.phase is TurnPhase.CLOSED:
            return
        tally = self.stores.setdefault((self.phase, step, store), StoreTally())
        tally.calls += 1
        tally.seconds += seconds

    def report(self, phase: TurnPhase, phase_seconds: float) -> dict[TurnStep, StepReport]:
        """Return phase's steps in time order, with OTHER as the phase's uncovered time."""
        named = {step: seconds for (p, step), seconds in self.steps.items() if p is phase}
        untimed = [s for (p, s, _) in self.stores if p is phase and s not in named]
        stepped = [
            *named,
            *dict.fromkeys(s for s in untimed if s is not TurnStep.OTHER),
            TurnStep.OTHER,
        ]
        report = {
            step: StepReport(
                seconds=named.get(step, 0.0),
                stores={
                    store: tally
                    for (p, s, store), tally in self.stores.items()
                    if p is phase and s is step
                },
            )
            for step in stepped
        }
        report[TurnStep.OTHER].seconds = max(phase_seconds - sum(named.values()), 0.0)
        return report


@dataclass
class _StepScope:
    """The step a task is inside; closed once the step ends, though tasks it spawned live on."""

    step: TurnStep
    open: bool = True


_turn: ContextVar[TurnTimings | None] = ContextVar("turn_timings", default=None)
_scope: ContextVar[_StepScope | None] = ContextVar("turn_step", default=None)


def begin_turn_timings(started: float | None = None) -> TurnTimings:
    """Start a request's timings, arrived at started, and make them current for everything it spawns."""
    timings = TurnTimings(started=started)
    _turn.set(timings)
    return timings


def current_turn_timings() -> TurnTimings | None:
    return _turn.get()


def close_ingress() -> dict[TurnStep, StepReport] | None:
    """End the current request's ingress at its turn's accept and return its steps; None outside one."""
    timings = _turn.get()
    if timings is None or timings.started is None or timings.phase is not TurnPhase.INGRESS:
        return None
    report = timings.report(TurnPhase.INGRESS, time.perf_counter() - timings.started)
    timings.enter(TurnPhase.CLOSED)
    return report


@contextmanager
def turn_step(step: TurnStep) -> Iterator[None]:
    """Time a step and attribute the store calls made inside it.

    A step opened inside another records nothing of its own: the outer step
    owns that time, so the named steps never sum past their phase. Outside a
    request (workers, scripts) it is a no-op.
    """
    timings = _turn.get()
    enclosing = _scope.get()
    if timings is None or (enclosing is not None and enclosing.open):
        yield
        return
    phase = timings.phase
    scope = _StepScope(step)
    token = _scope.set(scope)
    started = time.perf_counter()
    try:
        yield
    finally:
        scope.open = False  # pragma: no mutate — None reads as closed too
        _scope.reset(token)
        timings.add_step(phase, step, time.perf_counter() - started)


def record_store_call(store: Store, seconds: float) -> None:
    """Attribute one store round trip to the current turn: its open step, else BACKGROUND or OTHER."""
    timings = _turn.get()
    if timings is None:
        return
    timings.add_store_call(_attributed_step(_scope.get()), store, seconds)


def _attributed_step(scope: _StepScope | None) -> TurnStep:
    if scope is None:
        return TurnStep.OTHER
    return scope.step if scope.open else TurnStep.BACKGROUND


def _ms(seconds: float) -> float:
    return round(seconds * 1000.0, 2)


def render_reports(
    reports: Mapping[TurnPhase, Mapping[TurnStep, StepReport]],
) -> dict[str, dict[str, dict[str, float]]]:
    """Flatten phase reports for the wide event: {phase: {step: {ms, <store>_calls, <store>_ms}}}."""
    return {
        phase.value: {
            step.value: {
                "ms": _ms(report.seconds),
                **{
                    field: value
                    for store, tally in report.stores.items()
                    for field, value in (
                        (f"{store.value}_calls", tally.calls),
                        (f"{store.value}_ms", _ms(tally.seconds)),
                    )
                },
            }
            for step, report in steps.items()
        }
        for phase, steps in reports.items()
    }
