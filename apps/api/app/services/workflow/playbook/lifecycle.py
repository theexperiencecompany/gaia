"""The playbook lifecycle as one pure state machine.

A playbook moves between run statuses under three counters — ``suspect_streak``,
``heal_attempts`` and ``revision`` — and the rules for which event touches
which counter used to live in docstrings across the repository, the worker and
the check module. Every rule is here now, as a total function over (state,
event), so the repository's atomic writes and the worker's limit checks are
derived from one definition instead of agreeing by convention.

The rules, stated once:

* A **replay** records its outcome. ``SUCCESS`` clears the reason and the
  suspect streak. ``FAILED`` records the reason and leaves the streak alone. A
  ``SUSPECT`` records the reason and grows the streak, but only when the run
  says it counts and the playbook was not already suspect: two replays of one
  body racing to the same verdict are one suspect, not two.
* A **heal run that completed** without rewriting spends one heal attempt on
  the body it was healing.
* A **rewrite** starts a new body: status back to ``NOT_RUN``, reason cleared,
  revision bumped. The suspect streak survives on purpose — a rewrite is how a
  heal answers a suspect replay, and a playbook that keeps coming back suspect
  must still reach the limit. The heal attempts survive too: a rewrite out of
  a heal run (the body was ``FAILED`` or ``SUSPECT``) spends one and carries
  the count, and a rewrite of a body never replayed (``NOT_RUN``, a second
  write in the same run) carries it unchanged, so a body rewritten after every
  failed replay must still reach the limit. Only a trusted replay (the body
  was ``SUCCESS``) clears either.
* A playbook is **discarded** when its heal attempts or its suspect streak
  reach their limit, or when the workflow it was written for has changed
  underneath it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import assert_never

from app.constants.agents import PLAYBOOK_HEAL_ATTEMPT_LIMIT, PLAYBOOK_SUSPECT_STREAK_LIMIT
from app.models.playbook_models import PlaybookDocument, PlaybookRunOutcome, PlaybookRunStatus

#: Statuses a fire answers with a heal run rather than a replay: the last run
#: stopped partway, or finished with a result the record did not trust.
HEAL_STATUSES = frozenset({PlaybookRunStatus.FAILED, PlaybookRunStatus.SUSPECT})


class DiscardReason(str, Enum):
    """Why the worker dropped a playbook. Stored on the workflow, read in Loki."""

    STALE_WORKFLOW_HASH = "stale_workflow_hash"
    HEAL_ATTEMPTS_EXHAUSTED = "heal_attempts_exhausted"
    SUSPECT_STREAK_EXHAUSTED = "suspect_streak_exhausted"


@dataclass(frozen=True, slots=True)
class PlaybookLifecycle:
    """The lifecycle fields of a playbook, and nothing else."""

    status: PlaybookRunStatus
    reason: str | None
    suspect_streak: int
    heal_attempts: int
    revision: int

    @classmethod
    def of(cls, playbook: PlaybookDocument) -> PlaybookLifecycle:
        return cls(
            status=playbook.last_run_status,
            reason=playbook.last_run_reason,
            suspect_streak=playbook.suspect_streak,
            heal_attempts=playbook.heal_attempts,
            revision=playbook.revision,
        )


@dataclass(frozen=True, slots=True)
class Replayed:
    """A replay of the stored body finished with this outcome."""

    outcome: PlaybookRunOutcome


@dataclass(frozen=True, slots=True)
class HealCompleted:
    """A heal run reached its decision and left the body as it was."""


@dataclass(frozen=True, slots=True)
class Rewritten:
    """The body was written again, by an authoring or a heal run."""


PlaybookEvent = Replayed | HealCompleted | Rewritten


def _advance(
    state: PlaybookLifecycle,
    *,
    reason: str | None,
    status: PlaybookRunStatus | None = None,
    suspect_streak: int | None = None,
    heal_attempts: int | None = None,
    revision: int | None = None,
) -> PlaybookLifecycle:
    """The state with the given fields changed; ``dataclasses.replace`` with the
    state's own type kept rather than the generic one. ``reason`` is always
    stated: a transition either carries one or clears it, never inherits it."""
    return PlaybookLifecycle(
        status=state.status if status is None else status,
        reason=reason,
        suspect_streak=state.suspect_streak if suspect_streak is None else suspect_streak,
        heal_attempts=state.heal_attempts if heal_attempts is None else heal_attempts,
        revision=state.revision if revision is None else revision,
    )


#: A body that has never earned trust: freshly written, nothing recorded against it.
UNTRUSTED = PlaybookLifecycle(
    status=PlaybookRunStatus.NOT_RUN, reason=None, suspect_streak=0, heal_attempts=0, revision=0
)


def transition(state: PlaybookLifecycle, event: PlaybookEvent) -> PlaybookLifecycle:
    """The lifecycle after ``event``. Total over every (status, event) pair."""
    match event:
        case Rewritten():
            return _advance(
                state,
                status=PlaybookRunStatus.NOT_RUN,
                reason=None,
                heal_attempts=_attempts_after_rewrite(state),
                revision=state.revision + 1,
            )
        case HealCompleted():
            return _advance(state, reason=state.reason, heal_attempts=state.heal_attempts + 1)
        case Replayed(outcome=outcome):
            return _after_replay(state, outcome)
        case _:
            assert_never(event)


def _attempts_after_rewrite(state: PlaybookLifecycle) -> int:
    match state.status:
        case PlaybookRunStatus.SUCCESS:
            return 0
        case PlaybookRunStatus.NOT_RUN:
            return state.heal_attempts
        case PlaybookRunStatus.FAILED | PlaybookRunStatus.SUSPECT:
            return state.heal_attempts + 1
        case _:
            assert_never(state.status)


def _after_replay(state: PlaybookLifecycle, outcome: PlaybookRunOutcome) -> PlaybookLifecycle:
    match outcome.status:
        case PlaybookRunStatus.SUCCESS:
            return _advance(state, status=outcome.status, reason=None, suspect_streak=0)
        case PlaybookRunStatus.FAILED:
            return _advance(state, status=outcome.status, reason=outcome.reason)
        case PlaybookRunStatus.SUSPECT:
            grows = outcome.counts_toward_streak and state.status is not PlaybookRunStatus.SUSPECT
            return _advance(
                state,
                status=outcome.status,
                reason=outcome.reason,
                suspect_streak=state.suspect_streak + (1 if grows else 0),
            )
        case PlaybookRunStatus.NOT_RUN:
            raise ValueError("a replay cannot end with the playbook not run")
        case _:
            assert_never(outcome.status)


def streak_grows(state: PlaybookLifecycle, outcome: PlaybookRunOutcome) -> bool:
    """Whether recording ``outcome`` grows the suspect streak from ``state``.

    The one question the repository has to answer without the state in hand:
    a plain ``$inc`` cannot be conditional on the stored status, so the write
    matches on it instead. This is the rule that match encodes.
    """
    return transition(state, Replayed(outcome)).suspect_streak > state.suspect_streak


def grows_from_untrusted(outcome: PlaybookRunOutcome) -> bool:
    """Whether ``outcome`` grows the streak of a body that is not already suspect.

    The repository cannot read the stored status before it writes, so it writes
    conditionally on it; this is the rule that decides whether the growing
    write is even attempted. Defined through :func:`transition` so it cannot
    drift from the table.
    """
    return streak_grows(UNTRUSTED, outcome)


def needs_heal(state: PlaybookLifecycle) -> bool:
    """Whether the next fire runs the agent with the heal brief instead of a replay."""
    return state.status in HEAL_STATUSES


def discard_reason(state: PlaybookLifecycle) -> DiscardReason | None:
    """Why the playbook should be dropped before another fire spends a run on it.

    Checked at both points the worker can drop one: before a heal run, when the
    body has already had its attempts, and right after a suspect replay is
    recorded, when the streak may have just reached its limit.
    """
    if state.status is PlaybookRunStatus.SUSPECT and (
        state.suspect_streak >= PLAYBOOK_SUSPECT_STREAK_LIMIT
    ):
        return DiscardReason.SUSPECT_STREAK_EXHAUSTED
    if needs_heal(state) and state.heal_attempts >= PLAYBOOK_HEAL_ATTEMPT_LIMIT:
        return DiscardReason.HEAL_ATTEMPTS_EXHAUSTED
    return None
