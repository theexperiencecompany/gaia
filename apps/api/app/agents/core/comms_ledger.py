"""What one comms attempt still owes: the user messages it was given that nothing has closed yet.

The conversation runner opens a ledger per attempt under the run's comms_run key. A message
closes only when a tool names it: answered, react, stay_silent or call_executor; or when the
run ends on words, which answer every message still open. Each records its closure here; the step drains
closures and settles replies from them.
A run without that key (every run the runner did not start) has no ledger and closes nothing.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from langchain_core.runnables import RunnableConfig

from app.models.agent_config import AgentConfigurable, agent_configurable


class Closing(StrEnum):
    """How a message was closed."""

    ANSWERED = "answered"
    REACTED = "reacted"
    SILENT = "silent"
    HANDED = "handed"


@dataclass(frozen=True)
class Closure:
    """Messages one tool call closed, by log seq; a reaction also names the messages it lands on."""

    how: Closing
    seqs: tuple[int, ...]
    emoji: str | None = None
    # A reaction may land on a message a hand-off already closed: it acknowledges, closing nothing more.
    reacted: tuple[int, ...] = ()


class NotOpenError(ValueError):
    """A tool named a message this run was not given, or one already closed."""


@dataclass
class _Ledger:
    # Log seq -> message id, for every message given to the run.
    given: dict[int, str] = field(default_factory=dict)
    # Seqs given and not closed yet.
    open: set[int] = field(default_factory=set)
    # Closed since the step last drained: one model step may close a message twice (react + hand-off).
    closed: list[Closure] = field(default_factory=list)


# In-process like the attempt feed: the attempt and its graph run share one event loop.
_LEDGERS: dict[str, _Ledger] = {}


def open_ledger(run_id: str, messages: Mapping[int, str]) -> None:
    """Start the attempt's ledger owing messages, log seq -> message id."""
    _LEDGERS[run_id] = _Ledger(given=dict(messages), open=set(messages))


def owe(run_id: str, messages: Mapping[int, str]) -> None:
    """Add messages handed to the running attempt."""
    ledger = _LEDGERS[run_id]
    ledger.given.update(messages)
    ledger.open.update(messages)


def close_ledger(run_id: str) -> None:
    _LEDGERS.pop(run_id, None)


def drain(run_id: str) -> list[Closure]:
    """Return the closures recorded since the last drain."""
    ledger = _LEDGERS[run_id]
    closed = list(ledger.closed)
    ledger.closed.clear()
    return closed


def still_open(run_id: str) -> dict[int, str]:
    ledger = _LEDGERS[run_id]
    return {seq: ledger.given[seq] for seq in sorted(ledger.open)}


def answer_open(run_id: str) -> bool:
    """Close every message still open on the run as answered; False when none is open."""
    ledger = _LEDGERS[run_id]
    if not ledger.open:
        return False
    ledger.closed.append(Closure(how=Closing.ANSWERED, seqs=tuple(sorted(ledger.open))))
    ledger.open.clear()
    return True


def named(config: RunnableConfig, seqs: Sequence[int]) -> tuple[str, ...] | None:
    """Return the message ids of seqs, all still open on the run's ledger; None for a run with no ledger."""
    ledger = _ledger_of(config)
    return None if ledger is None else _checked(ledger, seqs)


def close(
    config: RunnableConfig, how: Closing, seqs: Sequence[int], emoji: str | None = None
) -> tuple[str, ...] | None:
    """Close seqs on the run's ledger and return their message ids; None for a run with no ledger."""
    ledger = _ledger_of(config)
    if ledger is None:
        return None
    named = tuple(dict.fromkeys(seqs))
    if how is Closing.REACTED and named and all(seq in ledger.given for seq in named):
        closing = tuple(seq for seq in named if seq in ledger.open)
        ledger.open.difference_update(closing)
        ledger.closed.append(Closure(how=how, seqs=closing, emoji=emoji, reacted=named))
        return tuple(ledger.given[seq] for seq in named)
    ids = _checked(ledger, named)
    ledger.open.difference_update(named)
    ledger.closed.append(Closure(how=how, seqs=named))
    return ids


def _ledger_of(config: RunnableConfig) -> _Ledger | None:
    configurable: AgentConfigurable = agent_configurable(config)
    run_id = configurable.get("comms_run")
    return _LEDGERS.get(run_id) if run_id is not None else None


def _checked(ledger: _Ledger, seqs: Sequence[int]) -> tuple[str, ...]:
    """Return the ids of seqs; each must be open, or closed by a call of the same model step."""
    closing = tuple(dict.fromkeys(seqs))
    just_closed = {seq for closure in ledger.closed for seq in closure.seqs}
    unknown = [seq for seq in closing if seq not in ledger.open | just_closed]
    if not closing or unknown:
        open_now = ", ".join(f"#{seq}" for seq in sorted(ledger.open)) or "none"
        raise NotOpenError(
            f"name messages still open in this conversation (open now: {open_now}); "
            f"not open: {', '.join(f'#{seq}' for seq in unknown) or 'no ids given'}"
        )
    return tuple(ledger.given[seq] for seq in closing)
