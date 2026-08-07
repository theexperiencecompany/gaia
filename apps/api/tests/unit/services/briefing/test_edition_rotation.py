"""Brutal unit tests for the weekly-edition shuffled-cycle rotation law.

``advance_rotation`` is pure given an injected ``random.Random``, so every test
here seeds its own RNG and asserts on real output — no mocking of the module
under test. Because the sequencing is genuinely randomized, most assertions
pin *invariants* the law guarantees (permutation, no early repeat, no
same-family boundary) rather than a specific shuffle output — those
invariants hold for every seed, so they are exact, not probabilistic.
"""

import random

import pytest

from app.models.user_models import EditionRotation
from app.services.briefing.edition_rotation import advance_rotation

FAMILIES_3 = ["alpha", "beta", "gamma"]


@pytest.mark.unit
class TestSixConsecutiveDraws:
    def test_two_full_permutations_with_no_boundary_repeat(self) -> None:
        rng = random.Random(1234)
        state: EditionRotation | None = None
        draws: list[str] = []
        for _ in range(6):
            family, state = advance_rotation(state, FAMILIES_3, rng)
            draws.append(family)

        first_cycle, second_cycle = draws[:3], draws[3:]
        # Fails if a cycle skips or duplicates a family (e.g. index/list drift).
        assert sorted(first_cycle) == sorted(FAMILIES_3)
        assert sorted(second_cycle) == sorted(FAMILIES_3)
        # Fails if the avoid_first swap in _reshuffle is removed or broken.
        assert draws[3] != draws[2]


@pytest.mark.unit
class TestPropertySweep:
    @pytest.mark.parametrize("family_count", [2, 3, 4, 5])
    @pytest.mark.parametrize("seed", range(50))
    def test_three_full_cycles_are_permutations_with_boundary_rule(
        self, seed: int, family_count: int
    ) -> None:
        families = [f"family_{i}" for i in range(family_count)]
        rng = random.Random(seed)
        state: EditionRotation | None = None
        draws: list[str] = []
        for _ in range(family_count * 3):
            family, state = advance_rotation(state, families, rng)
            draws.append(family)

        cycles = [draws[i * family_count : (i + 1) * family_count] for i in range(3)]
        for cycle in cycles:
            # Fails if reshuffle only fires sometimes (a stuck/duplicated family).
            assert sorted(cycle) == sorted(families)

        if family_count > 1:
            for i in range(1, 3):
                # Fails if the avoid_first swap is dropped: a cycle could open
                # on the family the previous cycle just closed on.
                assert cycles[i][0] != cycles[i - 1][-1]


@pytest.mark.unit
class TestSingleFamily:
    def test_always_returns_the_only_family_and_state_stays_valid(self) -> None:
        rng = random.Random(7)
        state: EditionRotation | None = None
        for _ in range(5):
            family, state = advance_rotation(state, ["only"], rng)
            assert family == "only"
            # len(cycle) == 1 means the avoid_first swap can never fire, so the
            # cycle trivially repeats the same family every draw by design.
            assert state.cycle == ["only"]
            assert state.index == 0


@pytest.mark.unit
class TestFamilyAddedMidCycle:
    def test_reshuffles_to_new_three_cycle_respecting_boundary(self) -> None:
        # Mid-cycle state: 2-family cycle ["a", "b"] currently pointing at "b"
        # (index=1). A third family "c" is now in the registry.
        state = EditionRotation(cycle=["a", "b"], index=1)
        families = ["a", "b", "c"]
        rng = random.Random(99)

        family, next_state = advance_rotation(state, families, rng)

        # Discard rule: the stale 2-cycle is thrown away and reshuffled as a
        # fresh 3-cycle containing every current family.
        assert sorted(next_state.cycle) == sorted(families)
        assert len(next_state.cycle) == 3
        # The returned family comes from the NEW cycle (index reset to 0, then
        # advanced), not from the discarded old cycle.
        assert next_state.cycle[0] == family
        assert next_state.index == 1
        # Boundary rule still applies against the OLD cycle's last element ("b").
        assert family != "b"


@pytest.mark.unit
class TestFamilyRemovedMidCycle:
    def test_discards_stale_cycle_and_reshuffles_to_remaining_families(self) -> None:
        # Mid-cycle state includes "c", which has since been removed.
        state = EditionRotation(cycle=["a", "b", "c"], index=1)
        families = ["a", "b"]
        rng = random.Random(4)

        family, next_state = advance_rotation(state, families, rng)

        assert sorted(next_state.cycle) == sorted(families)
        assert family in families
        assert next_state.cycle[0] == family


@pytest.mark.unit
class TestCorruptState:
    def test_out_of_range_index_reshuffles_without_raising(self) -> None:
        # index=5 is out of range for a 3-element cycle.
        state = EditionRotation(cycle=FAMILIES_3, index=5)
        rng = random.Random(11)

        family, next_state = advance_rotation(state, FAMILIES_3, rng)

        assert family in FAMILIES_3
        assert 0 <= next_state.index < len(next_state.cycle)
        assert sorted(next_state.cycle) == sorted(FAMILIES_3)


@pytest.mark.unit
class TestEmptyFamilies:
    def test_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="at least one family"):
            advance_rotation(None, [], random.Random(0))
