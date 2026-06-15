"""
Referral points engine — PURE.

No I/O, no time, no database. Given simple event counts it computes the
referrer's points, the (endless) milestone ladder, the next goal, total earned
months, and exactly which milestones a points change crosses. Keeping this pure
makes the program's economics trivially testable and free of hidden state; all
persistence and side effects live in ``referral_service`` / ``reward_service``.
"""

from collections.abc import Iterator

from app.constants.referrals import (
    FIXED_MILESTONES,
    LADDER_LOOKAHEAD_GOALS,
    POINTS_PER_ACTIVATION,
    POINTS_PER_RENEWAL,
    POINTS_PER_UPGRADE,
    RECURRING_REWARD_MONTHS,
    RECURRING_STEP_POINTS,
    SIGNUP_POINTS_LIFETIME_CAP,
)


def _iter_milestones() -> Iterator[tuple[int, int]]:
    """Yield ``(threshold, reward_months)`` for the endless ladder, ascending."""
    for milestone in FIXED_MILESTONES:
        yield milestone["threshold"], milestone["reward_months"]

    threshold = FIXED_MILESTONES[-1]["threshold"]
    while True:
        threshold += RECURRING_STEP_POINTS
        yield threshold, RECURRING_REWARD_MONTHS


def signup_points(activation_count: int) -> int:
    """Activation-derived points, capped over the referrer's lifetime.

    The cap is what prevents fake signups from minting more than the first
    reward — every goal beyond it requires real paid conversions.
    """
    return min(activation_count * POINTS_PER_ACTIVATION, SIGNUP_POINTS_LIFETIME_CAP)


def total_points(activation_count: int, upgrade_count: int, renewal_count: int) -> int:
    """Total referrer points from event counts."""
    return (
        signup_points(activation_count)
        + upgrade_count * POINTS_PER_UPGRADE
        + renewal_count * POINTS_PER_RENEWAL
    )


def total_earned_months(points: int) -> int:
    """Sum of reward months for every milestone whose threshold is reached."""
    earned = 0
    for threshold, reward_months in _iter_milestones():
        if threshold > points:
            break
        earned += reward_months
    return earned


def milestones_crossed(old_points: int, new_points: int) -> list[dict[str, int]]:
    """Milestones newly unlocked moving from ``old_points`` to ``new_points``.

    Returns ``[{"threshold", "reward_months"}]`` for thresholds in
    ``(old_points, new_points]``. Empty when points did not increase past a goal,
    which (together with the rewards-ledger uniqueness) keeps grants idempotent.
    """
    if new_points <= old_points:
        return []
    crossed: list[dict[str, int]] = []
    for threshold, reward_months in _iter_milestones():
        if threshold > new_points:
            break
        if threshold > old_points:
            crossed.append({"threshold": threshold, "reward_months": reward_months})
    return crossed


def next_goal(points: int) -> dict[str, int | float]:
    """The next unreached goal and progress toward it.

    ``points_into_current`` is measured from the previous milestone's threshold
    (0 when the user is below the first milestone), so the progress bar fills
    relative to the current segment rather than from zero each time.
    """
    previous_threshold = 0
    for threshold, reward_months in _iter_milestones():
        if threshold > points:
            span = threshold - previous_threshold
            into = points - previous_threshold
            progress = (into / span * 100) if span > 0 else 0.0
            return {
                "threshold": threshold,
                "reward_months": reward_months,
                "points_into_current": into,
                "progress_pct": round(progress, 1),
            }
        previous_threshold = threshold
    # Unreachable: the ladder is infinite.
    raise RuntimeError("milestone ladder exhausted")


def build_ladder(points: int) -> list[dict[str, int | str]]:
    """The ladder to render: every reached milestone plus a few upcoming goals.

    Each entry carries cumulative months and a status of ``done`` (reached),
    ``next`` (the immediate goal), or ``locked`` (further out).
    """
    next_threshold = next_goal(points)["threshold"]
    ladder: list[dict[str, int | str]] = []
    cumulative = 0
    upcoming_seen = 0

    for threshold, reward_months in _iter_milestones():
        cumulative += reward_months
        if threshold <= points:
            status = "done"
        elif threshold == next_threshold:
            status = "next"
        else:
            status = "locked"

        ladder.append(
            {
                "threshold": threshold,
                "reward_months": reward_months,
                "cumulative_months": cumulative,
                "status": status,
            }
        )

        if threshold > points:
            upcoming_seen += 1
            if upcoming_seen >= LADDER_LOOKAHEAD_GOALS:
                break

    return ladder
