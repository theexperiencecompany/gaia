"""Shuffled-cycle rotation for edition template families, per briefing kind.

The retention-loop spec's rotation law: each cycle is a random permutation of
every available family, consumed in order, so no family repeats until the whole
set has been used; the next cycle reshuffles and never opens with the family
the previous cycle closed on. State is per-user and per-kind (daily/weekly),
persisted on the user doc, so sequences survive restarts and families added
later simply join the next cycle.
"""

import random

from app.db.repositories.users import user_repository
from app.models.user_models import EditionRotation
from shared.py.wide_events import log


def advance_rotation(
    state: EditionRotation | None,
    families: list[str],
    rng: random.Random,
) -> tuple[str, EditionRotation]:
    """Pick the next family and return the state to persist.

    Pure given ``rng`` — the sequencing law is unit-tested by seeding it. A
    stale cycle (family set changed since it was shuffled) is discarded so a
    template added mid-cycle joins at the next shuffle rather than being
    skipped forever.
    """
    if not families:
        raise ValueError("edition rotation requires at least one family")

    cycle_valid = (
        state is not None
        and sorted(state.cycle) == sorted(families)
        and 0 <= state.index < len(state.cycle)
    )
    if state is None or not cycle_valid:
        previous_last = state.cycle[-1] if state is not None and state.cycle else None
        cycle = _reshuffle(families, rng, avoid_first=previous_last)
        state = EditionRotation(cycle=cycle, index=0)

    assert state is not None
    family = state.cycle[state.index]

    next_index = state.index + 1
    if next_index < len(state.cycle):
        return family, EditionRotation(cycle=state.cycle, index=next_index)

    # Cycle exhausted: reshuffle for next time, never opening on today's family
    # (the no-same-family-across-the-boundary clause).
    return family, EditionRotation(cycle=_reshuffle(families, rng, avoid_first=family), index=0)


def _reshuffle(families: list[str], rng: random.Random, *, avoid_first: str | None) -> list[str]:
    cycle = list(families)
    rng.shuffle(cycle)
    if len(cycle) > 1 and avoid_first is not None and cycle[0] == avoid_first:
        swap = rng.randrange(1, len(cycle))
        cycle[0], cycle[swap] = cycle[swap], cycle[0]
    return cycle


async def choose_edition_family(user_id: str, *, kind: str, families: list[str]) -> str:
    """Advance the user's persisted rotation for ``kind`` and return the family."""
    state = await user_repository.get_edition_rotation(user_id, kind)
    family, next_state = advance_rotation(state, families, random.Random())
    await user_repository.set_edition_rotation(user_id, kind, next_state)
    log.info(
        "briefing.edition_family_chosen",
        user_id=user_id,
        kind=kind,
        family=family,
        cycle_index=next_state.index,
    )
    return family
