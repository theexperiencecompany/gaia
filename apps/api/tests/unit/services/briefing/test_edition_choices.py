"""Storing which daily editions the user keeps on or favours, and refusing a rotation with none."""

from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tests.factories import make_user_id
from tests.helpers import captured_wide_event

from app.constants.briefing import EditionChoice, EditionFamily
from app.services.briefing.edition_choices import briefing_editions, set_edition_choices
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.briefing.editions.explorer_render import explorer_family_names
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import SettingsBriefingEditionsUpdated

USER_ID = make_user_id()


@dataclass
class _Seams:
    store: AsyncMock
    capture: MagicMock


@pytest.fixture
def seams() -> Iterator[_Seams]:
    with (
        patch(
            "app.services.briefing.edition_choices.user_repository.set_briefing_editions",
            new_callable=AsyncMock,
        ) as store,
        patch("app.services.briefing.edition_choices.capture") as capture,
    ):
        yield _Seams(store=store, capture=capture)


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
        async with captured_wide_event() as event:
            view = await set_edition_choices(
                USER_ID,
                {
                    "menu": EditionChoice.OFF,
                    "memo": EditionChoice.OFF,
                    "swiss": EditionChoice.FAVOURITE,
                    "postal": EditionChoice.ON,
                },
            )

        seams.store.assert_awaited_once_with(
            USER_ID,
            {
                "menu": EditionChoice.OFF,
                "memo": EditionChoice.OFF,
                "swiss": EditionChoice.FAVOURITE,
            },
        )
        seams.capture.assert_called_once_with(
            UserId(USER_ID),
            SettingsBriefingEditionsUpdated(
                editions_off=2, editions_favourited=1, editions_total=len(DAILY_FAMILY_WEIGHTS)
            ),
        )
        assert event["audit"] == [
            {"msg": "briefing editions updated", "actor": USER_ID, "off": 2, "favourites": 1}
        ]
        assert {e.family: e.choice for e in view.editions}[
            EditionFamily.SWISS
        ] == EditionChoice.FAVOURITE

    async def test_one_edition_left_on_is_accepted(self, seams: _Seams) -> None:
        choices: dict[str, EditionChoice] = {
            f: EditionChoice.OFF for f in DAILY_FAMILY_WEIGHTS if f != "swiss"
        }

        await set_edition_choices(USER_ID, choices)

        seams.store.assert_awaited_once_with(USER_ID, choices)

    async def test_every_edition_off_is_refused_and_nothing_is_stored(self, seams: _Seams) -> None:
        with pytest.raises(AppError) as refused:
            await set_edition_choices(
                USER_ID, dict.fromkeys(DAILY_FAMILY_WEIGHTS, EditionChoice.OFF)
            )

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
                USER_ID, {"weekly": EditionChoice.OFF, "gone": EditionChoice.FAVOURITE}
            )

        error = refused.value
        assert (error.status_code, error.message, error.why, error.fix) == (
            422,
            "Not a daily edition: gone, weekly",
            "Only the daily edition families can be turned off or favourited",
            "Choose from the editions GET /briefings/editions lists",
        )
        seams.store.assert_not_awaited()
