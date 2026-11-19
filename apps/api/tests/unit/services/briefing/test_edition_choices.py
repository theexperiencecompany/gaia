"""Storing which daily editions the user keeps on or favours, and refusing a rotation with none."""

from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.briefing import EditionChoice
from app.services.briefing.edition_choices import briefing_editions, set_edition_choices
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.briefing.editions.explorer_render import explorer_family_names
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import SettingsBriefingEditionsUpdated

_USER = "507f1f77bcf86cd799439011"


@dataclass
class _Seams:
    store: AsyncMock
    capture: MagicMock
    log: MagicMock


@pytest.fixture
def seams() -> Iterator[_Seams]:
    with (
        patch(
            "app.services.briefing.edition_choices.user_repository.set_briefing_editions",
            new_callable=AsyncMock,
        ) as store,
        patch("app.services.briefing.edition_choices.capture") as capture,
        patch("app.services.briefing.edition_choices.log") as log,
    ):
        yield _Seams(store=store, capture=capture, log=log)


@pytest.mark.unit
class TestBriefingEditions:
    def test_every_daily_family_is_listed_by_name_and_on_unless_chosen(self) -> None:
        view = briefing_editions({"menu": EditionChoice.OFF, "gone": EditionChoice.FAVOURITE})

        names = explorer_family_names()
        assert [e.family for e in view.editions] == sorted(
            DAILY_FAMILY_WEIGHTS, key=lambda family: names[family]
        )
        assert {e.family: e.choice for e in view.editions} == {
            family: EditionChoice.OFF if family == "menu" else EditionChoice.ON
            for family in DAILY_FAMILY_WEIGHTS
        }
        assert next(e for e in view.editions if e.family == "postal").name == "Air Mail"

    def test_no_edition_is_named_after_the_product(self) -> None:
        names = [edition.name for edition in briefing_editions({}).editions]

        assert [name for name in names if "GAIA" in name] == []


@pytest.mark.unit
class TestSetEditionChoices:
    async def test_only_off_and_favourite_are_stored_and_the_counts_are_captured(
        self, seams: _Seams
    ) -> None:
        view = await set_edition_choices(
            _USER,
            {
                "menu": EditionChoice.OFF,
                "memo": EditionChoice.OFF,
                "swiss": EditionChoice.FAVOURITE,
                "postal": EditionChoice.ON,
            },
        )

        seams.store.assert_awaited_once_with(
            _USER,
            {
                "menu": EditionChoice.OFF,
                "memo": EditionChoice.OFF,
                "swiss": EditionChoice.FAVOURITE,
            },
        )
        seams.capture.assert_called_once_with(
            UserId(_USER),
            SettingsBriefingEditionsUpdated(
                editions_off=2, editions_favourited=1, editions_total=len(DAILY_FAMILY_WEIGHTS)
            ),
        )
        seams.log.audit.assert_called_once_with(
            "briefing editions updated", actor=_USER, off=2, favourites=1
        )
        assert {e.family: e.choice for e in view.editions}["swiss"] == EditionChoice.FAVOURITE

    async def test_one_edition_left_on_is_accepted(self, seams: _Seams) -> None:
        choices = {f: EditionChoice.OFF for f in DAILY_FAMILY_WEIGHTS if f != "swiss"}

        await set_edition_choices(_USER, choices)

        seams.store.assert_awaited_once_with(_USER, choices)

    async def test_every_edition_off_is_refused_and_nothing_is_stored(self, seams: _Seams) -> None:
        with pytest.raises(AppError) as refused:
            await set_edition_choices(_USER, dict.fromkeys(DAILY_FAMILY_WEIGHTS, EditionChoice.OFF))

        error = refused.value
        assert (error.status_code, error.message, error.why, error.fix) == (
            422,
            "Keep at least one edition on",
            "Every brief is drawn from the editions you keep on",
            "Turn one edition back on",
        )
        seams.store.assert_not_awaited()
        seams.capture.assert_not_called()

    async def test_families_that_are_not_daily_editions_are_refused_by_name(
        self, seams: _Seams
    ) -> None:
        with pytest.raises(AppError) as refused:
            await set_edition_choices(
                _USER, {"weekly": EditionChoice.OFF, "gone": EditionChoice.FAVOURITE}
            )

        error = refused.value
        assert (error.status_code, error.message, error.why, error.fix) == (
            422,
            "Not a daily edition: gone, weekly",
            "Only the daily edition families can be turned off or favourited",
            "Choose from the editions GET /notifications/preferences/briefing-editions lists",
        )
        seams.store.assert_not_awaited()
