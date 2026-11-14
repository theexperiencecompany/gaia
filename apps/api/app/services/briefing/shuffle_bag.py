"""A per-user shuffle bag: every member appears its weight in times per pass.

Each pass is a fresh random order of the whole pool, consumed one draw a day. No
member lands on two consecutive draws (including across the reshuffle boundary) and
no pass repeats the previous order. The edition family, the Air Mail stamp city and
the painting are drawn this way; the state is the small ShuffleBag persisted per user.
"""

from collections.abc import Mapping, Set
from itertools import pairwise
import random

from app.models.user_models import ShuffleBag

# Rejection sampling bound: valid orders are the overwhelming majority for any
# pool this module serves, so hitting it means the pool cannot be arranged.
_MAX_SHUFFLE_ATTEMPTS = 1000


def _pool(weights: Mapping[str, int]) -> list[str]:
    return sorted(member for member, count in weights.items() for _ in range(count))


def _valid(
    order: list[str], *, previous: list[str] | None, last: str | None, eligible: Set[str]
) -> bool:
    if order == previous or order[0] == last or order[0] not in eligible:
        return False
    return all(a != b for a, b in pairwise(order))


def _shuffle(
    weights: Mapping[str, int],
    rng: random.Random,
    *,
    previous: list[str] | None,
    last: str | None,
    eligible: Set[str],
) -> list[str]:
    order = _pool(weights)
    for _ in range(_MAX_SHUFFLE_ATTEMPTS):
        rng.shuffle(order)
        if _valid(order, previous=previous, last=last, eligible=eligible):
            return list(order)
    raise ValueError(
        f"No order of {dict(weights)} opening on an eligible member keeps every repeat apart"
    )


def _next_eligible(state: ShuffleBag, eligible: Set[str]) -> ShuffleBag | None:
    """Swap the pass's next eligible member into today's slot; None when none is left."""
    for slot in range(state.index, len(state.order)):
        if state.order[slot] in eligible:
            order = list(state.order)
            order[state.index], order[slot] = order[slot], order[state.index]
            return ShuffleBag(order=order, index=state.index)
    return None


def draw(
    state: ShuffleBag | None,
    weights: Mapping[str, int],
    rng: random.Random,
    *,
    eligible: Set[str] | None = None,
) -> tuple[str, ShuffleBag]:
    """Today's member and the state to persist for tomorrow.

    eligible narrows today's member over a pool of distinct members: the pass hands out
    its next eligible one, and the others keep their turn later in the same pass.
    """
    allowed = weights.keys() if eligible is None else eligible
    current = state is not None and sorted(state.order) == _pool(weights)
    pending = _next_eligible(state, allowed) if state is not None and current else None
    if pending is not None:
        member = pending.order[pending.index]
        return member, ShuffleBag(order=pending.order, index=pending.index + 1)
    last = state.order[state.index - 1] if state and 0 < state.index <= len(state.order) else None
    order = _shuffle(
        weights, rng, previous=state.order if state else None, last=last, eligible=allowed
    )
    return order[0], ShuffleBag(order=order, index=1)
