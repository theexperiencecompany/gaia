"""The playbook lifecycle, exhaustively: every (status, event) pair, and the two
limits, as a table. A rule that lived in a docstring is a rule nobody can prove
still holds; this is where each one is proved.
"""

from itertools import product

import pytest

from app.constants.agents import PLAYBOOK_HEAL_ATTEMPT_LIMIT, PLAYBOOK_SUSPECT_STREAK_LIMIT
from app.models.playbook_models import PlaybookRunOutcome, PlaybookRunStatus
from app.services.workflow.playbook.lifecycle import (
    HEAL_STATUSES,
    DiscardReason,
    HealCompleted,
    PlaybookLifecycle,
    Replayed,
    Rewritten,
    discard_reason,
    needs_heal,
    streak_grows,
    transition,
)

STATUSES = list(PlaybookRunStatus)
REPLAY_OUTCOMES = [
    PlaybookRunOutcome(PlaybookRunStatus.SUCCESS),
    PlaybookRunOutcome(PlaybookRunStatus.FAILED, reason="stopped"),
    PlaybookRunOutcome(PlaybookRunStatus.SUSPECT, reason="empty where the last run had items"),
    PlaybookRunOutcome(
        PlaybookRunStatus.SUSPECT, reason="narration said so", counts_toward_streak=False
    ),
]


def _state(
    status: PlaybookRunStatus, *, streak: int = 1, heals: int = 1, revision: int = 3
) -> PlaybookLifecycle:
    return PlaybookLifecycle(
        status=status,
        reason="why" if status is not PlaybookRunStatus.SUCCESS else None,
        suspect_streak=streak,
        heal_attempts=heals,
        revision=revision,
    )


@pytest.mark.unit
class TestTransitionTable:
    """Every pair, so a status or an event added later cannot be left undefined."""

    @pytest.mark.parametrize(("status", "outcome"), list(product(STATUSES, REPLAY_OUTCOMES)))
    def test_every_replay_from_every_status(
        self, status: PlaybookRunStatus, outcome: PlaybookRunOutcome
    ) -> None:
        before = _state(status)

        after = transition(before, Replayed(outcome))

        assert after.status is outcome.status
        assert after.revision == before.revision and after.heal_attempts == before.heal_attempts, (
            "a replay never touches the body's revision or its heal attempts"
        )
        if outcome.status is PlaybookRunStatus.SUCCESS:
            assert after.reason is None and after.suspect_streak == 0
        elif outcome.status is PlaybookRunStatus.FAILED:
            assert after.reason == outcome.reason and after.suspect_streak == before.suspect_streak
        else:
            assert after.reason == outcome.reason
            grew = outcome.counts_toward_streak and status is not PlaybookRunStatus.SUSPECT
            assert after.suspect_streak == before.suspect_streak + (1 if grew else 0)

    @pytest.mark.parametrize("status", STATUSES)
    def test_a_rewrite_starts_a_new_body_but_keeps_the_streak(
        self, status: PlaybookRunStatus
    ) -> None:
        before = _state(status, streak=1, heals=1, revision=3)

        after = transition(before, Rewritten())

        # A rewrite out of a heal run spends one attempt on the body it replaces
        # and carries the count forward; only a trusted replay clears it. Seen
        # live: a body whose $ask no model could fill failed every replay, the
        # agent finishing the fire rewrote it identically, and a reset count
        # meant the cycle never reached the limit.
        assert after == PlaybookLifecycle(
            status=PlaybookRunStatus.NOT_RUN,
            reason=None,
            suspect_streak=1,
            heal_attempts={
                PlaybookRunStatus.SUCCESS: 0,
                PlaybookRunStatus.NOT_RUN: 1,
                PlaybookRunStatus.FAILED: 2,
                PlaybookRunStatus.SUSPECT: 2,
            }[status],
            revision=4,
        )

    def test_a_second_write_in_the_same_heal_run_keeps_the_attempt_the_first_carried(
        self,
    ) -> None:
        """Seen live: the executor was re-prompted to decide and wrote the body
        twice; the second write found a NOT_RUN body and reset the count."""
        state = _state(PlaybookRunStatus.FAILED, heals=1)
        first = transition(state, Rewritten())
        second = transition(first, Rewritten())

        assert first.heal_attempts == 2
        assert second.heal_attempts == 2

    def test_a_body_that_is_rewritten_after_every_failed_replay_still_reaches_the_limit(
        self,
    ) -> None:
        state = _state(PlaybookRunStatus.NOT_RUN, streak=0, heals=0, revision=1)
        failed = PlaybookRunOutcome(status=PlaybookRunStatus.FAILED, reason="ask unanswered")
        for spent in range(1, PLAYBOOK_HEAL_ATTEMPT_LIMIT + 1):
            state = transition(state, Replayed(failed))
            assert discard_reason(state) is None, spent
            state = transition(state, Rewritten())
            assert state.heal_attempts == spent
        state = transition(state, Replayed(failed))

        assert discard_reason(state) is DiscardReason.HEAL_ATTEMPTS_EXHAUSTED

    @pytest.mark.parametrize("status", STATUSES)
    def test_a_completed_heal_spends_one_attempt_and_nothing_else(
        self, status: PlaybookRunStatus
    ) -> None:
        before = _state(status)

        after = transition(before, HealCompleted())

        assert after == PlaybookLifecycle(
            status=before.status,
            reason=before.reason,
            suspect_streak=before.suspect_streak,
            heal_attempts=before.heal_attempts + 1,
            revision=before.revision,
        )

    def test_a_replay_cannot_leave_the_playbook_not_run(self) -> None:
        with pytest.raises(ValueError, match="cannot end with the playbook not run"):
            transition(
                _state(PlaybookRunStatus.SUCCESS),
                Replayed(PlaybookRunOutcome(PlaybookRunStatus.NOT_RUN)),
            )


@pytest.mark.unit
class TestTwoSuspectsAreOne:
    """Two replays of one body racing to the same verdict are one suspect."""

    def test_a_suspect_on_a_suspect_does_not_grow(self) -> None:
        outcome = PlaybookRunOutcome(PlaybookRunStatus.SUSPECT, reason="r")
        assert streak_grows(_state(PlaybookRunStatus.SUCCESS, streak=0), outcome) is True
        assert streak_grows(_state(PlaybookRunStatus.SUSPECT, streak=1), outcome) is False

    def test_the_narrations_opinion_never_grows_it(self) -> None:
        opinion = PlaybookRunOutcome(
            PlaybookRunStatus.SUSPECT, reason="r", counts_toward_streak=False
        )
        assert streak_grows(_state(PlaybookRunStatus.SUCCESS, streak=0), opinion) is False


@pytest.mark.unit
class TestLimits:
    @pytest.mark.parametrize("status", STATUSES)
    def test_only_a_stopped_or_distrusted_body_needs_healing(
        self, status: PlaybookRunStatus
    ) -> None:
        assert needs_heal(_state(status)) is (status in HEAL_STATUSES)

    def test_a_suspect_at_the_streak_limit_is_discarded_for_the_streak(self) -> None:
        state = _state(PlaybookRunStatus.SUSPECT, streak=PLAYBOOK_SUSPECT_STREAK_LIMIT, heals=0)
        assert discard_reason(state) is DiscardReason.SUSPECT_STREAK_EXHAUSTED

    @pytest.mark.parametrize("status", sorted(HEAL_STATUSES, key=str))
    def test_a_healing_body_at_the_attempt_limit_is_discarded_for_the_attempts(
        self, status: PlaybookRunStatus
    ) -> None:
        state = _state(status, streak=0, heals=PLAYBOOK_HEAL_ATTEMPT_LIMIT)
        assert discard_reason(state) is DiscardReason.HEAL_ATTEMPTS_EXHAUSTED

    @pytest.mark.parametrize("status", STATUSES)
    def test_under_both_limits_nothing_is_discarded(self, status: PlaybookRunStatus) -> None:
        state = _state(
            status, streak=PLAYBOOK_SUSPECT_STREAK_LIMIT - 1, heals=PLAYBOOK_HEAL_ATTEMPT_LIMIT - 1
        )
        assert discard_reason(state) is None

    def test_a_trusted_body_is_never_discarded_however_many_heals_it_once_had(self) -> None:
        state = _state(PlaybookRunStatus.SUCCESS, streak=0, heals=PLAYBOOK_HEAL_ATTEMPT_LIMIT + 5)
        assert discard_reason(state) is None
