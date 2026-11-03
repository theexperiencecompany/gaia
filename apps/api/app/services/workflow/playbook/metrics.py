"""Prometheus counters for playbook decisions and replays, the signal the playbook alerts read.

Every label is a closed set: the decision tool, its outcome, and a reason that is
a PlaybookRefusal or a DeclineKind value. Every series an alert reads is created
at zero on import, so the first refusal after a worker restart is an increase
from 0 rather than a new series increase() cannot see.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

from prometheus_client import Counter

from app.models.playbook_models import DeclineKind, PlaybookRefusal, PlaybookRunStatus
from app.services.storage.metrics import _register_once


class PlaybookDecisionTool(str, Enum):
    """The playbook tool a decision was made with."""

    WRITE = "write"
    DECLINE = "decline"
    DISABLE = "disable"


class PlaybookDecisionOutcome(str, Enum):
    """Whether the decision stood: written, recorded, or refused with a reason."""

    ACCEPTED = "accepted"
    REFUSED = "refused"
    #: The tool raised before it could decide: a bug, never the author's doing.
    ERROR = "error"


#: The reason label on a decision that needs none (a write that stood, a disable).
NO_REASON: Final = "none"

PLAYBOOK_DECISION_TOTAL = _register_once(
    "gaia_playbook_decision_total",
    lambda: Counter(
        name="gaia_playbook_decision_total",
        documentation="Playbook write/decline/disable decisions by outcome and reason",
        labelnames=("tool", "outcome", "reason"),
    ),
)

PLAYBOOK_REPLAY_TOTAL = _register_once(
    "gaia_playbook_replay_total",
    lambda: Counter(
        name="gaia_playbook_replay_total",
        documentation="Playbook replays by the outcome the record check gave them",
        labelnames=("status",),
    ),
)

ALL_PLAYBOOK_COLLECTORS: Final[tuple[Counter, ...]] = (
    PLAYBOOK_DECISION_TOTAL,
    PLAYBOOK_REPLAY_TOTAL,
)

#: The statuses a finished replay can end in; NOT_RUN is the absence of one.
REPLAY_STATUSES: Final = (
    PlaybookRunStatus.SUCCESS,
    PlaybookRunStatus.SUSPECT,
    PlaybookRunStatus.FAILED,
)


def record_write(outcome: PlaybookDecisionOutcome, refusal: PlaybookRefusal | None = None) -> None:
    """Count one write_playbook call; a refusal is labelled by its first problem's kind."""
    reason = refusal.value if refusal is not None else NO_REASON
    PLAYBOOK_DECISION_TOTAL.labels(PlaybookDecisionTool.WRITE.value, outcome.value, reason).inc()


def record_decline(kind: DeclineKind, *, refused: bool) -> None:
    """Count one decline_playbook call by its kind, and whether it was refused."""
    outcome = PlaybookDecisionOutcome.REFUSED if refused else PlaybookDecisionOutcome.ACCEPTED
    PLAYBOOK_DECISION_TOTAL.labels(
        PlaybookDecisionTool.DECLINE.value, outcome.value, kind.value
    ).inc()


def record_disable(*, refused: bool) -> None:
    """Count one disable_playbook call."""
    outcome = PlaybookDecisionOutcome.REFUSED if refused else PlaybookDecisionOutcome.ACCEPTED
    PLAYBOOK_DECISION_TOTAL.labels(
        PlaybookDecisionTool.DISABLE.value, outcome.value, NO_REASON
    ).inc()


def record_replay(status: PlaybookRunStatus) -> None:
    """Count one finished replay by the status its record check gave it."""
    PLAYBOOK_REPLAY_TOTAL.labels(status.value).inc()


def _create_alerted_series() -> None:
    for outcome in (PlaybookDecisionOutcome.ACCEPTED, PlaybookDecisionOutcome.ERROR):
        PLAYBOOK_DECISION_TOTAL.labels(PlaybookDecisionTool.WRITE.value, outcome.value, NO_REASON)
    for refusal in PlaybookRefusal:
        PLAYBOOK_DECISION_TOTAL.labels(
            PlaybookDecisionTool.WRITE.value, PlaybookDecisionOutcome.REFUSED.value, refusal.value
        )
    for status in REPLAY_STATUSES:
        PLAYBOOK_REPLAY_TOTAL.labels(status.value)


_create_alerted_series()
