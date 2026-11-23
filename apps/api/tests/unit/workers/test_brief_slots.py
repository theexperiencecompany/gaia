"""Brief runs spread across their hour: one stable minute per user, never the same second for all."""

from app.constants.brief_slots import BRIEF_SLOT_SPREAD_MINUTES
from app.workers.brief_slots import slot_minute


def test_a_users_minute_is_stable_and_inside_the_spread() -> None:
    assert slot_minute("user-1") == slot_minute("user-1")
    assert 0 <= slot_minute("user-1") < BRIEF_SLOT_SPREAD_MINUTES


def test_many_users_land_on_many_minutes() -> None:
    minutes = {slot_minute(f"user-{n}") for n in range(500)}

    assert minutes == set(range(BRIEF_SLOT_SPREAD_MINUTES))
