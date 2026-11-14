"""The per-user shuffle bag that picks each brief's edition family and stamp."""

from collections import Counter
from itertools import pairwise
import random

import pytest

from app.models.user_models import ShuffleBag
from app.services.briefing.editions import (
    DAILY_FAMILY_WEIGHTS,
    EXPLORER_RENDERER,
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


_WORKS = {f"w{i}": 1 for i in range(12)}
# Three frames, each fitting a different, overlapping share of the works.
_FITS = {
    "wide": frozenset(f"w{i}" for i in range(8)),
    "tall": frozenset(f"w{i}" for i in range(4, 12)),
    "any": frozenset(_WORKS),
}


@pytest.mark.unit
class TestEligibleDraw:
    def _hang(self, frames: list[str], seed: int) -> list[tuple[str, ShuffleBag]]:
        rng = random.Random(seed)
        state: ShuffleBag | None = None
        hung: list[tuple[str, ShuffleBag]] = []
        for frame in frames:
            work, state = draw(state, _WORKS, rng, eligible=_FITS[frame])
            hung.append((work, state))
        return hung

    def test_every_draw_fits_the_frame_it_was_drawn_for(self) -> None:
        frames = [random.Random(s).choice(list(_FITS)) for s in range(200)]

        for (work, _), frame in zip(self._hang(frames, seed=3), frames, strict=True):
            assert work in _FITS[frame]

    def test_no_work_repeats_within_a_pass_whatever_the_frames(self) -> None:
        for seed in range(30):
            frames = [random.Random(seed * 1000 + s).choice(list(_FITS)) for s in range(120)]
            passes: list[list[str]] = []
            for work, state in self._hang(frames, seed):
                if state.index == 1:
                    passes.append([])
                passes[-1].append(work)

            for hung in passes:
                assert len(hung) == len(set(hung)), hung

    def test_a_work_the_frame_cannot_take_keeps_its_turn_in_the_pass(self) -> None:
        order = ["w9", "w1", "w2"]

        work, state = draw(
            ShuffleBag(order=order, index=0),
            {"w1": 1, "w2": 1, "w9": 1},
            random.Random(1),
            eligible=frozenset({"w1", "w2"}),
        )

        assert work == "w1"
        assert state == ShuffleBag(order=["w1", "w9", "w2"], index=1)

    def test_a_pass_with_no_fitting_work_left_reshuffles_onto_one_that_fits(self) -> None:
        """Only w9 is left, which the frame cannot take; w1 went out yesterday."""
        for seed in range(30):
            spent = ShuffleBag(order=["w2", "w1", "w9"], index=2)

            work, state = draw(
                spent,
                {"w1": 1, "w2": 1, "w9": 1},
                random.Random(seed),
                eligible=frozenset({"w1", "w2"}),
            )

            assert work == "w2"
            assert state.index == 1 and sorted(state.order) == ["w1", "w2", "w9"]

    def test_a_frame_no_work_fits_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="eligible member"):
            draw(None, {"w1": 1}, random.Random(1), eligible=frozenset({"w9"}))


@pytest.mark.unit
class TestDailyFamilyWeights:
    def test_postal_is_twice_as_common_and_every_daily_family_is_in(self) -> None:
        assert DAILY_FAMILY_WEIGHTS["postal"] == 2
        assert set(DAILY_FAMILY_WEIGHTS) == set(EXPLORER_RENDERER) - {WEEKLY_FAMILY}
        assert "metromap" in DAILY_FAMILY_WEIGHTS
        assert all(w == 1 for f, w in DAILY_FAMILY_WEIGHTS.items() if f != "postal")

    def test_the_daily_bag_only_draws_families_that_have_a_renderer(self) -> None:
        picks, _ = _draws(10 * sum(DAILY_FAMILY_WEIGHTS.values()), DAILY_FAMILY_WEIGHTS)

        assert "edition" not in picks
        assert set(picks) <= set(EXPLORER_RENDERER)
