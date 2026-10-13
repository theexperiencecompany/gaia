"""Brutal unit tests for the weekly-edition shuffled-cycle rotation law.

``advance_rotation`` is pure given an injected ``random.Random``, so every test
here seeds its own RNG and asserts on real output — no mocking of the module
under test. Because the sequencing is genuinely randomized, most assertions
pin *invariants* the law guarantees (permutation, no early repeat, no
same-family boundary) rather than a specific shuffle output — those
invariants hold for every seed, so they are exact, not probabilistic.
"""

import random
from typing import Any

import pytest

from app.models.user_models import EditionRotation
from app.services.briefing import edition_rotation
from app.services.briefing.edition_rotation import advance_rotation, choose_edition_family

FAMILIES_3 = ["alpha", "beta", "gamma"]


class ScriptedRandom(random.Random):
    """A ``random.Random`` whose shuffle order and swap slot are fixed.

    The boundary rule ("never open a cycle on the family the previous one
    closed on") is only observable when the shuffle actually lands that family
    first — with a seeded RNG that happens by luck, so a test relying on it
    passes just as well with the avoid-first swap deleted. Scripting the order
    forces the collision on every run.
    """

    def __init__(self, order: list[str], swap_slot: int = 1) -> None:
        super().__init__()
        self.order = order
        self.swap_slot = swap_slot

    def shuffle(self, x: Any) -> None:
        x[:] = list(self.order)

    def randrange(self, *args: Any, **kwargs: Any) -> int:
        return self.swap_slot


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

    def test_index_equal_to_the_cycle_length_is_out_of_range_too(self) -> None:
        # The off-by-one boundary: index=3 addresses no element of a 3-element
        # cycle, so it must reshuffle. Accepting it would index past the end.
        state = EditionRotation(cycle=FAMILIES_3, index=3)
        rng = random.Random(11)

        family, next_state = advance_rotation(state, FAMILIES_3, rng)

        assert family in FAMILIES_3
        assert next_state.index == 1
        assert sorted(next_state.cycle) == sorted(FAMILIES_3)


@pytest.mark.unit
class TestBoundaryRuleOnADiscardedCycle:
    def test_the_discarded_cycles_last_family_never_opens_the_new_one(self) -> None:
        # The stale cycle closed on "beta"; the registry has since changed, so
        # it is discarded. The scripted shuffle deliberately puts "beta" first
        # in the replacement, and the avoid-first swap must move it to slot 1.
        state = EditionRotation(cycle=["delta", "alpha", "beta"], index=0)
        rng = ScriptedRandom(order=["beta", "gamma", "alpha"], swap_slot=1)

        family, next_state = advance_rotation(state, FAMILIES_3, rng)

        assert next_state.cycle == ["gamma", "beta", "alpha"]
        assert family == "gamma"
        assert next_state.index == 1


class FakeUserRepo:
    """``user_repository`` narrowed to the rotation accessors, real signatures
    kept so a call that drops or reorders an argument raises here."""

    def __init__(self, stored: dict[tuple[str, str], EditionRotation] | None = None) -> None:
        self.stored = stored or {}
        self.saved: list[tuple[str, str, EditionRotation]] = []

    async def get_edition_rotation(self, user_id: str, kind: str) -> EditionRotation | None:
        return self.stored.get((user_id, kind))

    async def set_edition_rotation(self, user_id: str, kind: str, state: EditionRotation) -> None:
        self.saved.append((user_id, kind, state))


@pytest.mark.unit
class TestChooseEditionFamily:
    """The persisted half: read this user's rotation for this kind, advance it,
    write it back. Nothing here reshuffles a cycle that is still running."""

    async def test_an_in_progress_cycle_is_continued_and_advanced_in_place(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = FakeUserRepo({("user-1", "weekly"): EditionRotation(cycle=FAMILIES_3, index=1)})
        monkeypatch.setattr(edition_rotation, "user_repository", repo)

        family = await choose_edition_family("user-1", kind="weekly", families=FAMILIES_3)

        assert family == "beta"
        assert repo.saved == [("user-1", "weekly", EditionRotation(cycle=FAMILIES_3, index=2))]

    async def test_a_user_with_no_rotation_yet_gets_a_fresh_cycle_persisted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = FakeUserRepo()
        monkeypatch.setattr(edition_rotation, "user_repository", repo)

        family = await choose_edition_family("user-1", kind="daily", families=FAMILIES_3)

        saved_user_id, saved_kind, saved_state = repo.saved[0]
        assert (saved_user_id, saved_kind) == ("user-1", "daily")
        assert sorted(saved_state.cycle) == sorted(FAMILIES_3)
        # The family just handed out is the one the new cycle opened on, and
        # the stored index already points past it.
        assert saved_state.cycle[0] == family
        assert saved_state.index == 1


@pytest.mark.unit
class TestEmptyFamilies:
    def test_raises_value_error(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            advance_rotation(None, [], random.Random(0))

        assert str(excinfo.value) == "edition rotation requires at least one family"
