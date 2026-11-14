"""A per-user shuffle bag: every member appears its weight in times per pass.

Each pass is a fresh random order of the whole pool, consumed one draw a day. No
member lands on two consecutive draws (including across the reshuffle boundary) and
no pass repeats the previous order. The edition family and the Air Mail stamp city
are both drawn this way; the state is the small ShuffleBag persisted per user.
"""

from collections.abc import Mapping
from itertools import pairwise
import random

from app.models.user_models import ShuffleBag

# Rejection sampling bound: valid orders are the overwhelming majority for any
# pool this module serves, so hitting it means the pool cannot be arranged.
_MAX_SHUFFLE_ATTEMPTS = 1000


def _pool(weights: Mapping[str, int]) -> list[str]:
    return sorted(member for member, count in weights.items() for _ in range(count))


def _valid(order: list[str], *, previous: list[str] | None, last: str | None) -> bool:
    if order == previous or (last is not None and order[0] == last):
        return False
    return all(a != b for a, b in pairwise(order))


def _shuffle(
    weights: Mapping[str, int], rng: random.Random, *, previous: list[str] | None, last: str | None
) -> list[str]:
    order = _pool(weights)
    for _ in range(_MAX_SHUFFLE_ATTEMPTS):
        rng.shuffle(order)
        if _valid(order, previous=previous, last=last):
            return list(order)
    raise ValueError(f"No order of {dict(weights)} keeps every repeat apart")


def draw(
    state: ShuffleBag | None, weights: Mapping[str, int], rng: random.Random
) -> tuple[str, ShuffleBag]:
    """Today's member and the state to persist for tomorrow."""
    current = state is not None and sorted(state.order) == _pool(weights)
    if state is not None and current and state.index < len(state.order):
        return state.order[state.index], ShuffleBag(order=state.order, index=state.index + 1)
    last = state.order[state.index - 1] if state and 0 < state.index <= len(state.order) else None
    order = _shuffle(weights, rng, previous=state.order if state else None, last=last)
    return order[0], ShuffleBag(order=order, index=1)
