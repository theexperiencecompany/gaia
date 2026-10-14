"""The per-user shuffle bag that picks each brief's edition family and stamp."""

from collections import Counter
from itertools import pairwise
import random

import pytest

from app.models.user_models import ShuffleBag
from app.services.briefing.editions import (
    DAILY_FAMILY_WEIGHTS,
    EXPLORER_RENDERER,
    FAMILY_EDITION,
    WEEKLY_FAMILY,
)
from app.services.briefing.shuffle_bag import draw

_WEIGHTS = {"postal": 2, "memo": 1, "swiss": 1, "receipt": 1}


def _draws(n: int, weights: dict[str, int], seed: int = 7) -> tuple[list[str], list[list[str]]]:
    rng = random.Random(seed)
    state: ShuffleBag | None = None
    picks: list[str] = []
    passes: list[list[str]] = []
    for _ in range(n):
        family, state = draw(state, weights, rng)
        if state.index == 1:
            passes.append(list(state.order))
        picks.append(family)
    return picks, passes


@pytest.mark.unit
class TestDraw:
    def test_every_family_appears_its_weight_before_anything_repeats(self) -> None:
        _, passes = _draws(5 * 10, _WEIGHTS)

        for order in passes:
            assert Counter(order) == Counter(_WEIGHTS)

    def test_no_family_lands_on_two_consecutive_days_even_across_a_reshuffle(self) -> None:
        for seed in range(40):
            picks, _ = _draws(5 * 30, _WEIGHTS, seed=seed)
            assert all(a != b for a, b in pairwise(picks)), picks

    def test_the_two_postal_days_are_never_back_to_back(self) -> None:
        for seed in range(40):
            picks, _ = _draws(5 * 30, _WEIGHTS, seed=seed)
            assert all(not (a == b == "postal") for a, b in pairwise(picks))

    def test_each_pass_is_a_fresh_order(self) -> None:
        _, passes = _draws(5 * 30, _WEIGHTS)

        assert all(a != b for a, b in pairwise(passes))

    def test_a_bag_whose_pool_changed_is_reshuffled_without_repeating_today(self) -> None:
        stale = ShuffleBag(order=["memo", "gone", "swiss"], index=1)

        family, state = draw(stale, _WEIGHTS, random.Random(1))

        assert Counter(state.order) == Counter(_WEIGHTS)
        assert state.index == 1
        assert family == state.order[0] != "memo"

    def test_an_impossible_pool_fails_loud(self) -> None:
        with pytest.raises(ValueError):
            draw(None, {"postal": 2}, random.Random(1))


@pytest.mark.unit
class TestDailyFamilyWeights:
    def test_postal_is_twice_as_common_and_every_daily_family_is_in(self) -> None:
        assert DAILY_FAMILY_WEIGHTS["postal"] == 2
        assert set(DAILY_FAMILY_WEIGHTS) == {FAMILY_EDITION, *EXPLORER_RENDERER} - {WEEKLY_FAMILY}
        assert "metromap" in DAILY_FAMILY_WEIGHTS
        assert all(w == 1 for f, w in DAILY_FAMILY_WEIGHTS.items() if f != "postal")
