"""Did we fail to conduct the test, or did the agent answer wrongly?

The harness has exactly one question to answer before it may grade anything, and
this module is the only place that answers it. Getting it wrong is the most
expensive defect the harness can have: a datastore that went away for four hours
was averaged into accuracy as 157 wrong answers, and one question type was
published as ``single-session-user 0/64`` when not one of those 64 questions was
ever asked.

Two rules live here, deliberately kept apart because they answer different
questions with different evidence:

``classify`` reads a *live exception* and says whether a backend the suite
depends on is unavailable — which must abort the run, because every case after
it would measure the outage rather than the agent.

``never_conducted`` reads a *journal record* and says whether that case ever
executed. It needs no exception and no signature table: a record carrying a
fault, an empty transcript and no scores is a case that never ran, whatever
raised it. That covers the outages, the harness's own crashes, and anything
neither list anticipated.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

import httpx

from .types import InfraError

# Exception types that can only ever mean "the thing we were talking to is not
# there". None of them can be produced by an agent giving a poor answer, which
# is what makes matching on the type alone safe.
_TRANSPORT_FAULTS: tuple[tuple[type[BaseException], str], ...] = (
    (httpx.ConnectError, "api"),
    (httpx.ConnectTimeout, "api"),
    (httpx.RemoteProtocolError, "api"),
    (httpx.ReadError, "api"),
    (httpx.WriteError, "api"),
    (ConnectionError, "api"),
    (BrokenPipeError, "api"),
)

# Faults that arrive as a generic exception type (usually ``RuntimeError``), so
# only the message identifies them. Every entry is anchored to a named backend
# and copied from something that actually exists — either an error text found in
# a journal record, or a literal ``raise`` in ``app/db`` (postgresql.py:147,
# chromadb.py:44/50/285, rabbitmq.py:85). None is invented, and none can be
# emitted by an agent answering a question.
#
# These are string matches against another module's messages, so they rot if
# those messages are reworded. ``never_conducted`` is deliberately not built on
# this table for exactly that reason — a re-grade must not depend on having
# guessed the wording right.
_FAULT_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("postgresql engine not available", "postgres"),
    ("the database system is shutting down", "postgres"),
    ("the database system is starting up", "postgres"),
    ("connection to server at", "postgres"),
    ("chromadb client not initialized", "chroma"),
    ("chromadb client could not be initialized", "chroma"),
    ("chromadb connection failed", "chroma"),
    ("failed to establish rabbitmq connection", "rabbitmq"),
    ("all connection attempts failed", "api"),
    ("server disconnected without sending a response", "api"),
    ("broken pipe", "api"),
    ("connect call failed", "api"),
    ("dev executor endpoint failed: http 5", "api"),
)


@dataclass(frozen=True)
class Fault:
    """An identified infrastructure outage: which backend, and what it said."""

    backend: str
    reason: str

    def as_infra_error(self) -> InfraError:
        """The exception the run loop aborts on."""
        return InfraError(self.backend, self.reason)


def classify(exc: BaseException) -> Fault | None:
    """The outage behind ``exc``, or ``None`` if it is not an outage.

    ``None`` does not mean the case succeeded — a harness bug is still a fault,
    and the run loop still records it as ``errored``. It means only that the run
    need not abort, because retrying elsewhere or continuing is sane.
    """
    if isinstance(exc, InfraError):
        return Fault(exc.backend, exc.reason)
    for fault_type, backend in _TRANSPORT_FAULTS:
        if isinstance(exc, fault_type):
            return Fault(backend, f"{type(exc).__name__}: {exc}")
    message = f"{type(exc).__name__}: {exc}".lower()
    for signature, backend in _FAULT_SIGNATURES:
        if signature in message:
            return Fault(backend, f"{type(exc).__name__}: {exc}")
    return None


def confirmed_down(fault: Fault) -> bool:
    """Whether the backend the fault points at is actually unreachable.

    A transport exception's TYPE cannot say which peer dropped the connection:
    an httpx.RemoteProtocolError from the remote LLM provider's gateway looks
    identical to one from our own API. Aborting on type alone killed three
    LongMemEval runs whose API was healthy the whole time — the provider's
    CDN hiccuped. So before a run aborts, the accused backend is probed; if it
    answers, the fault was elsewhere and the case is an ordinary retryable
    error. Signature-matched faults (a Postgres raise, a Chroma raise) name
    their backend unambiguously and are not second-guessed.
    """
    if fault.backend != "api":
        return True
    # 127.0.0.1, never localhost: uvicorn binds IPv4 only and macOS resolves
    # localhost to ::1 first, so the probe's ConnectError read as "confirmed
    # down" and aborted runs whose API was healthy the whole time.
    base = os.environ.get("EVALS_DEV_API_BASE", "http://127.0.0.1:9460")
    try:
        response = httpx.get(f"{base}/health", timeout=5.0)
    except Exception:
        return True
    return response.status_code >= 500


def never_conducted(record: dict[str, Any]) -> bool:
    """Whether this journal record is a case that never actually ran.

    Deliberately independent of :func:`classify`: it asks what the record *is*,
    not what raised it. A case that hit a fault and produced no transcript, no
    tool calls and no scores did not answer anything — grading it as a wrong
    answer invents a measurement that was never taken. This is what makes the
    re-grade complete rather than limited to outages we happened to anticipate:
    a ``NameError`` in our own runner is just as much "not conducted" as a dead
    datastore, and both must leave the accuracy denominator.

    A case that errored *after* producing output is not covered here — it has
    real evidence in it, and the run loop already recorded it as ``errored``.
    """
    if not record.get("error"):
        return False
    return not (
        record.get("text")
        or record.get("messages")
        or record.get("tool_calls")
        or record.get("scores")
    )
