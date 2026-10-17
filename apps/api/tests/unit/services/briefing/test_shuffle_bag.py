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

    def test_a_bag_mid_pass_hands_out_its_next_member_without_reshuffling(self) -> None:
        order = ["postal", "memo", "postal", "swiss", "receipt"]

        family, state = draw(ShuffleBag(order=order, index=2), _WEIGHTS, random.Random(1))

        assert family == "postal"
        assert state == ShuffleBag(order=order, index=3)

    def test_the_reshuffle_never_opens_with_yesterdays_member(self) -> None:
        """A stale bag one draw in still knows what went out yesterday."""
        for seed in range(30):
            stale = ShuffleBag(order=["a", "gone"], index=1)

            family, _ = draw(stale, {"a": 1, "b": 1}, random.Random(seed))

            assert family == "b"

    def test_a_stale_bag_never_drawn_from_puts_no_limit_on_the_first_pick(self) -> None:
        firsts = {
            draw(ShuffleBag(order=["gone", "a"], index=0), {"a": 1, "b": 1}, random.Random(s))[0]
            for s in range(30)
        }

        assert firsts == {"a", "b"}

    def test_an_impossible_pool_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="keeps every repeat apart"):
            draw(None, {"postal": 2}, random.Random(1))


@pytest.mark.unit
class TestDailyFamilyWeights:
    def test_postal_is_twice_as_common_and_every_daily_family_is_in(self) -> None:
        assert DAILY_FAMILY_WEIGHTS["postal"] == 2
        assert set(DAILY_FAMILY_WEIGHTS) == {FAMILY_EDITION, *EXPLORER_RENDERER} - {WEEKLY_FAMILY}
        assert "metromap" in DAILY_FAMILY_WEIGHTS
        assert all(w == 1 for f, w in DAILY_FAMILY_WEIGHTS.items() if f != "postal")
