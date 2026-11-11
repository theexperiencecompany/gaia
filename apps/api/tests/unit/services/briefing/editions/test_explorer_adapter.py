"""Unit tests for the BriefingPayload -> explorer ed adapter.

build_ed is pure, so every test drives the real function and pins the exact ed values
the vendored JS templates read.
"""

from typing import Any

import pytest
from tests.factories import make_brief_item as _item

from app.constants.briefing import BriefAction
from app.models.briefing_models import BriefingPayload
from app.services.briefing.editions.codes import Symbology, code_geometry
from app.services.briefing.editions.explorer_adapter import ExplorerArt, build_ed
from app.services.briefing.editions.stamps import stamp_for

LINK = "https://heygaia.link/aB3dE5gH7jK"
ASSETS = {"ART1": "data:image/jpeg;base64,AAAA", "BAND": "data:image/webp;base64,BBBB"}
ART: ExplorerArt = {
    "src": "data:image/jpeg;base64,AAAA",
    "title": "Wheat Field with Cypresses",
    "artist": "Vincent van Gogh",
    "year": "1889",
    "medium": "oil on canvas",
}


def _payload(**overrides: Any) -> BriefingPayload:
    payload: dict[str, Any] = {
        "kicker": "",
        "template_family": "swiss",
        "date": "2026-07-05",
        "headline": "",
        "lede": "Three things need you before noon.",
        "stats": [],
        "sections": [],
        "mood": "clear",
        "caption": "",
        "link": LINK,
    }
    payload.update(overrides)
    return BriefingPayload.model_validate(payload)


def _build(
    payload: BriefingPayload, *, generated_local: str = "6:02 AM", family: str = "swiss"
) -> dict[str, Any]:
    return dict(
        build_ed(
            payload,
            edition_no=42,
            generated_local=generated_local,
            assets=ASSETS,
            art=ART,
            family=family,
        )
    )


@pytest.mark.unit
class TestDateline:
    def test_iso_date_expands_into_every_date_field(self) -> None:
        ed = _build(_payload())

        assert ed["weekday"] == "Sunday"
        assert ed["day"] == 5
        assert ed["month"] == "July"
        assert ed["monthShort"] == "Jul"
        assert ed["year"] == 2026
        assert ed["dateLong"] == "Sunday, 5 July 2026"

    @pytest.mark.parametrize(
        ("iso", "weekday", "month", "short"),
        [
            ("2026-01-05", "Monday", "January", "Jan"),
            ("2026-03-07", "Saturday", "March", "Mar"),
            ("2026-12-31", "Thursday", "December", "Dec"),
        ],
    )
    def test_weekday_and_month_names_come_from_the_calendar(
        self, iso: str, weekday: str, month: str, short: str
    ) -> None:
        ed = _build(_payload(date=iso))

        assert ed["weekday"] == weekday
        assert ed["month"] == month
        assert ed["monthShort"] == short

    def test_unparseable_date_degrades_to_blanks_and_keeps_the_raw_string(self) -> None:
        ed = _build(_payload(date="last tuesday"))

        assert ed["weekday"] == ""
        assert ed["day"] == 0
        assert ed["month"] == ""
        assert ed["monthShort"] == ""
        assert ed["year"] == 0
        assert ed["dateLong"] == "last tuesday"

    def test_empty_date_degrades_without_raising(self) -> None:
        ed = _build(_payload(date=""))

        assert ed["dateLong"] == ""
        assert ed["year"] == 0


@pytest.mark.unit
class TestEditionScalars:
    def test_edition_number_fills_both_slots_the_templates_read(self) -> None:
        ed = _build(_payload())

        assert ed["n"] == 42
        assert ed["editionNo"] == 42

    def test_deck_is_the_headline_for_a_deck_only_family(self) -> None:
        ed = _build(_payload(headline="Quiet morning."))

        assert ed["deck"] == "Quiet morning."

    def test_empty_headline_becomes_an_empty_deck(self) -> None:
        ed = _build(_payload(headline=""))

        assert ed["deck"] == ""

    def test_text_is_not_pre_escaped_because_templates_escape_their_own(self) -> None:
        ed = _build(_payload(headline="Ana & Bo <b>ship</b>"))

        assert ed["deck"] == "Ana & Bo <b>ship</b>"

    @pytest.mark.parametrize(
        ("generated", "expected24"),
        [
            ("6:02 AM", "06:02"),
            ("12:00 AM", "00:00"),
            ("12:30 PM", "12:30"),
            ("1:05 PM", "13:05"),
            ("11:59 pm", "23:59"),
            ("09:07 AM", "09:07"),
        ],
    )
    def test_generated_time_is_converted_to_24_hour(self, generated: str, expected24: str) -> None:
        ed = _build(_payload(), generated_local=generated)

        assert ed["time"] == generated
        assert ed["time24"] == expected24

    @pytest.mark.parametrize("generated", ["", "just now", "6.02 AM", "6:2 AM", "18:30"])
    def test_unparseable_generation_time_passes_through_unchanged(self, generated: str) -> None:
        ed = _build(_payload(), generated_local=generated)

        assert ed["time"] == generated
        assert ed["time24"] == generated


@pytest.mark.unit
class TestArt:
    def test_the_painting_is_passed_through_verbatim(self) -> None:
        assert _build(_payload())["art"] == ART

    def test_assets_map_is_passed_through_verbatim(self) -> None:
        ed = _build(_payload())

        assert ed["assets"] == ASSETS


_WEEK = {
    "days": [{"you": i, "gaia": 7 - i} for i in range(7)],
    "ahead": [{"date": "2026-07-06", "title": "Board meeting"}],
}
_TODAY_EVENT = {"date": "2026-07-05", "start": "11:00", "title": "Sequoia"}

_SECTION = {
    "numeral": "I",
    "title": "Needs you",
    "items": [
        _item("Acme MSA renewal", "you", action=BriefAction.APPROVE, count=3),
        _item("Sync Stripe", "failed"),
        _item("Investor update", "lookback"),
    ],
}


@pytest.mark.unit
class TestBlocks:
    def test_the_drawn_blocks_are_passed_in_reading_order(self) -> None:
        ed = _build(
            _payload(
                sections=[_SECTION],
                blocks=[
                    {"kind": "note", "text": "Mornings are tight."},
                    {"kind": "items", "section": 0},
                ],
            )
        )

        assert [b["kind"] for b in ed["blocks"]] == ["note", "items"]

    def test_the_weekly_family_lists_the_week_ahead_as_its_calendar(self) -> None:
        ed = _build(_payload(week=_WEEK, calendar=[_TODAY_EVENT]), family="weekly")

        assert ed["blocks"] == [
            {
                "kind": "calendar",
                "events": [
                    {
                        "t12": None,
                        "t24": None,
                        "day": "Mon",
                        "title": "Board meeting",
                        "detail": None,
                        "logo": "googlecalendar",
                    }
                ],
                "more": 0,
                "first": None,
                "last": None,
            }
        ]

    def test_a_daily_family_lists_todays_calendar(self) -> None:
        ed = _build(_payload(week=_WEEK, calendar=[_TODAY_EVENT]), family="swiss")

        assert [
            e["title"] for b in ed["blocks"] if b["kind"] == "calendar" for e in b["events"]
        ] == ["Sequoia"]

    def test_todays_events_are_not_named_by_a_weekday_and_the_apps_read_carry_their_marks(
        self,
    ) -> None:
        ed = _build(
            _payload(calendar=[_TODAY_EVENT], sources_read=["Gmail"]),
            family="swiss",
        )

        [calendar] = [b for b in ed["blocks"] if b["kind"] == "calendar"]
        assert [e["day"] for e in calendar["events"]] == [None]
        assert ed["sources"] == [{"name": "Gmail", "logo": "gmail"}]


@pytest.mark.unit
class TestHeadline:
    @pytest.mark.parametrize("family", ["memo", "postal", "broadsheet", "receipt"])
    def test_every_family_leads_with_the_headline(self, family: str) -> None:
        ed = _build(_payload(headline="Two replies need you"), family=family)

        assert ed["deck"] == "Two replies need you"

    def test_an_empty_day_draws_no_block_instead_of_a_placeholder_row(self) -> None:
        assert _build(_payload(), family="boardingpass")["blocks"] == []


@pytest.mark.unit
class TestRecipient:
    def test_the_full_and_first_name_address_the_edition(self) -> None:
        ed = _build(_payload(recipient_name="  Aryan   Randeriya "))

        assert ed["recipient"] == {"name": "Aryan Randeriya", "first": "Aryan"}

    def test_the_first_name_is_only_the_first_of_several_words(self) -> None:
        ed = _build(_payload(recipient_name="Mary Jane Watson"))

        assert ed["recipient"] == {"name": "Mary Jane Watson", "first": "Mary"}

    @pytest.mark.parametrize("name", [None, "", "   "])
    def test_no_name_leaves_no_recipient(self, name: str | None) -> None:
        assert _build(_payload(recipient_name=name))["recipient"] is None


@pytest.mark.unit
class TestStats:
    def test_figures_come_from_the_tallies(self) -> None:
        ed = _build(_payload(tallies={"done_by_you": 2, "done_by_gaia": 1}))

        assert ed["stats"] == {
            "done": 3,
            "you": 2,
            "gaia": 1,
            "mail": None,
            "focus": None,
        }

    def test_a_zero_figure_is_unknown_so_the_template_draws_nothing(self) -> None:
        stats = _build(_payload(tallies={"done_by_you": 1, "done_by_gaia": 0}))["stats"]

        assert (stats["done"], stats["you"], stats["gaia"]) == (1, 1, None)

    def test_work_done_only_by_gaia_still_draws_the_figures(self) -> None:
        stats = _build(_payload(tallies={"done_by_you": 0, "done_by_gaia": 2}))["stats"]

        assert (stats["done"], stats["you"], stats["gaia"]) == (2, None, 2)

    def test_no_tallies_leaves_no_stats_block(self) -> None:
        assert _build(_payload())["stats"] is None

    def test_zero_tallies_leave_no_stats_block(self) -> None:
        payload = _payload(tallies={"done_by_you": 0, "done_by_gaia": 0})

        assert _build(payload)["stats"] is None


@pytest.mark.unit
class TestAwaiting:
    def test_counts_every_todo_behind_the_drawn_asks(self) -> None:
        payload = _payload(sections=[_SECTION], blocks=[{"kind": "items", "section": 0}])

        assert _build(payload)["awaiting"] == 4

    def test_an_ask_the_edition_does_not_draw_is_not_billed(self) -> None:
        assert _build(_payload(sections=[_SECTION]))["awaiting"] is None

    def test_nothing_awaiting_is_unknown_so_the_template_bills_no_figure(self) -> None:
        section = {"numeral": "I", "title": "Work", "items": [_item("Deck", "lookback")]}
        payload = _payload(sections=[section], blocks=[{"kind": "items", "section": 0}])

        assert _build(payload)["awaiting"] is None


@pytest.mark.unit
class TestStamp:
    def test_air_mail_carries_the_drawn_citys_stamp(self) -> None:
        ed = _build(_payload(stamp_city="paris"), family="postal")

        assert ed["stamp"] == stamp_for("paris")

    def test_a_legacy_air_mail_brief_without_a_city_keeps_the_template_axis(self) -> None:
        assert _build(_payload(), family="postal")["stamp"] is None

    def test_other_families_carry_no_stamp(self) -> None:
        assert _build(_payload(stamp_city="paris"), family="swiss")["stamp"] is None


@pytest.mark.unit
class TestCodes:
    @pytest.mark.parametrize(
        ("family", "symbologies"),
        [
            ("invoice", [Symbology.QR]),
            ("receipt", [Symbology.CODE128]),
            ("boardingpass", [Symbology.CODE128, Symbology.PDF417]),
            ("swiss", []),
        ],
    )
    def test_a_family_carries_only_the_codes_it_prints_each_encoding_the_link(
        self, family: str, symbologies: list[Symbology]
    ) -> None:
        codes = _build(_payload(), family=family)["codes"]

        assert codes == {s: code_geometry(s, LINK) for s in symbologies}

    def test_a_family_that_prints_a_code_refuses_a_brief_without_a_link(self) -> None:
        with pytest.raises(ValueError, match="invoice"):
            _build(_payload(link=None), family="invoice")

    def test_a_family_without_a_code_renders_a_legacy_brief_without_a_link(self) -> None:
        assert _build(_payload(link=None), family="swiss")["codes"] == {}
