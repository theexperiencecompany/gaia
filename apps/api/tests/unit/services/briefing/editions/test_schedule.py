"""The weekday schedule that picks each brief's edition family."""

import pytest

from app.services.briefing.editions import (
    EDITION_SCHEDULE,
    EXPLORER_RENDERER,
    family_for_date,
    renderer_for,
)
from app.services.briefing.editions.explorer_render import explorer_family_ids


@pytest.mark.unit
class TestEditionSchedule:
    @pytest.mark.parametrize(
        ("iso_date", "family"),
        [
            ("2026-10-12", "memo"),
            ("2026-10-13", "swiss"),
            ("2026-10-14", "postal"),
            ("2026-10-15", "broadsheet"),
            ("2026-10-16", "playbill"),
            ("2026-10-17", "receipt"),
            ("2026-10-18", "weekly"),
        ],
    )
    def test_each_weekday_has_its_family(self, iso_date: str, family: str) -> None:
        assert family_for_date(iso_date) == family

    def test_the_same_weekday_always_picks_the_same_family(self) -> None:
        assert family_for_date("2026-10-14") == family_for_date("2027-01-06")

    def test_every_scheduled_family_is_a_registered_renderer(self) -> None:
        assert sorted(EDITION_SCHEDULE) == list(range(7))
        for family in EDITION_SCHEDULE.values():
            assert renderer_for(family) is EXPLORER_RENDERER[family]

    def test_unscheduled_families_stay_renderable(self) -> None:
        unscheduled = set(explorer_family_ids()) - set(EDITION_SCHEDULE.values())

        assert len(unscheduled) == 13
        assert all(renderer_for(family) is not None for family in unscheduled)

    def test_a_malformed_date_fails_loud(self) -> None:
        with pytest.raises(ValueError):
            family_for_date("last tuesday")
