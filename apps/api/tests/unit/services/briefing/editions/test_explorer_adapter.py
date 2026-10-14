"""Unit tests for the BriefingPayload -> explorer ed adapter.

build_ed is pure, so every test drives the real function and pins the exact ed values
the vendored JS templates read.
"""

from typing import Any

import pytest

from app.models.briefing_models import BriefingPayload
from app.services.briefing.editions.explorer_adapter import build_ed
from app.services.briefing.editions.explorer_render import explorer_family_ids

ASSETS = {"ART1": "data:image/jpeg;base64,AAAA", "BAND": "data:image/webp;base64,BBBB"}
CREDIT = "Wheat Field with Cypresses — Vincent van Gogh"


def _item(text: str, kind: str = "note") -> dict[str, Any]:
    return {"text": text, "kind": kind}


def _payload(**overrides: Any) -> BriefingPayload:
    payload: dict[str, Any] = {
        "kicker": "",
        "date": "2026-07-05",
        "headline": "",
        "lede": "Three things need you before noon.",
        "stats": [],
        "sections": [],
        "mood": "clear",
        "caption": "",
    }
    payload.update(overrides)
    return BriefingPayload.model_validate(payload)


def _build(payload: BriefingPayload, *, generated_local: str = "6:02 AM") -> dict[str, Any]:
    return dict(
        build_ed(
            payload,
            edition_no=42,
            generated_local=generated_local,
            assets=ASSETS,
            art_credit=CREDIT,
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
    def test_credit_splits_into_title_and_artist_on_the_em_dash(self) -> None:
        ed = _build(_payload())

        assert ed["art"] == {
            "src": "data:image/jpeg;base64,AAAA",
            "title": "Wheat Field with Cypresses",
            "artist": "Vincent van Gogh",
            "year": 1889,
            "medium": "oil on canvas",
        }

    def test_credit_without_an_em_dash_keeps_the_whole_string_as_the_title(self) -> None:
        ed = build_ed(
            _payload(),
            edition_no=1,
            generated_local="6:02 AM",
            assets=ASSETS,
            art_credit="  Untitled  ",
        )

        assert ed["art"]["title"] == "Untitled"
        assert ed["art"]["artist"] == ""

    def test_only_the_first_em_dash_splits_the_credit(self) -> None:
        ed = build_ed(
            _payload(),
            edition_no=1,
            generated_local="6:02 AM",
            assets=ASSETS,
            art_credit="A — B — C",
        )

        assert ed["art"]["title"] == "A"
        assert ed["art"]["artist"] == "B — C"

    def test_missing_art_asset_leaves_an_empty_src(self) -> None:
        ed = build_ed(
            _payload(),
            edition_no=1,
            generated_local="6:02 AM",
            assets={"BAND": "data:image/webp;base64,BBBB"},
            art_credit=CREDIT,
        )

        assert ed["art"]["src"] == ""

    def test_assets_map_is_passed_through_verbatim(self) -> None:
        ed = _build(_payload())

        assert ed["assets"] == ASSETS


@pytest.mark.unit
class TestContent:
    """Each bucket holds what its heading promises.

    "Today" is the user's calendar led by the first thing waiting on them;
    GAIA's work (and any note) is "while you slept"; every ask, including a
    failed run to retry, is a decision. A status word is never a headline.
    """

    def _daily(self, **overrides: Any) -> BriefingPayload:
        return _payload(
            sections=[
                {
                    "numeral": "I",
                    "title": "NEEDS YOU",
                    "items": [
                        _item("Approve the Priya reply", "you"),
                        _item("Sync Stripe invoices", "failed"),
                    ],
                },
                {
                    "numeral": "II",
                    "title": "GAIA'S WORK",
                    "items": [
                        _item("Investor update", "lookback"),
                        _item("Q4 hiring plan", "gaia"),
                    ],
                },
            ],
            calendar=[
                {
                    "date": "2026-07-05",
                    "start": "11:00",
                    "title": "Sequoia",
                    "location": "Menlo Park",
                },
                {"date": "2026-07-05", "start": None, "title": "Offsite"},
            ],
            **overrides,
        )

    def test_today_is_the_calendar_only(self) -> None:
        today = _build(self._daily())["content"]["today"]

        assert today == [
            {
                "time": "11:00 AM",
                "t24": "11:00",
                "label": "Sequoia",
                "note": "Menlo Park",
                "tag": "",
            },
            {"time": None, "t24": None, "label": "Offsite", "note": None, "tag": ""},
        ]

    @pytest.mark.parametrize("family", sorted({"edition", *explorer_family_ids()}))
    def test_no_item_appears_in_two_sections_in_any_family(self, family: str) -> None:
        content = build_ed(
            self._daily(),
            edition_no=1,
            generated_local="",
            assets=ASSETS,
            art_credit=CREDIT,
            family=family,
        )["content"]

        labels = [
            row["label"]
            for bucket in ("today", "overnight", "decisions")
            for row in content[bucket]
            if row["label"] != "—"
        ]
        assert len(labels) == len(set(labels)), labels

    def test_a_failed_run_is_a_decision_to_retry_never_a_today_item(self) -> None:
        content = _build(self._daily())["content"]

        assert content["decisions"] == [
            {"verb": "Approve", "label": "the Priya reply", "note": None},
            {"verb": "Retry", "label": "Sync Stripe invoices", "note": None},
        ]
        assert all("Stripe" not in row["label"] for row in content["today"])

    def test_gaias_work_is_overnight_with_its_state(self) -> None:
        overnight = _build(self._daily())["content"]["overnight"]

        assert [(r["label"], r["tag"]) for r in overnight] == [
            ("Investor update", "DONE"),
            ("Q4 hiring plan", "IN PROGRESS"),
        ]

    def test_an_empty_day_leaves_every_bucket_empty_instead_of_a_fake_row(self) -> None:
        """Regression: empty buckets rendered as "EOD Nothing on the calendar today" rows."""
        content = _build(_payload(sections=[]))["content"]

        assert (content["today"], content["overnight"], content["decisions"]) == ([], [], [])

    def test_a_note_reads_as_overnight_without_a_tag(self) -> None:
        overnight = _build(
            _payload(sections=[{"numeral": "I", "title": "X", "items": [_item("Heads up")]}])
        )["content"]["overnight"]

        assert overnight == [{"t24": None, "label": "Heads up", "note": None, "tag": ""}]


@pytest.mark.unit
class TestHeadline:
    @pytest.mark.parametrize("family", ["memo", "postal", "broadsheet"])
    def test_families_with_a_title_slot_get_both_lines(self, family: str) -> None:
        ed = build_ed(
            _payload(headline="Two replies need you"),
            edition_no=1,
            generated_local="",
            assets=ASSETS,
            art_credit=CREDIT,
            family=family,
        )

        assert ed["headline"] == "Two replies need you"
        assert ed["deck"] == "Three things need you before noon."

    @pytest.mark.parametrize("family", ["playbill", "receipt", "swiss"])
    def test_a_deck_only_family_leads_with_the_headline(self, family: str) -> None:
        ed = build_ed(
            _payload(headline="Two replies need you"),
            edition_no=1,
            generated_local="",
            assets=ASSETS,
            art_credit=CREDIT,
            family=family,
        )

        assert ed["deck"] == "Two replies need you"


@pytest.mark.unit
class TestFixedSlots:
    """Some vendored families index fixed item slots.

    The founder fixture always held three today, three overnight and two decision items.
    A family handed fewer threw in the page script, and Chromium shipped a blank 2px PNG.
    """

    def _sparse(self) -> BriefingPayload:
        return _payload(
            sections=[{"numeral": "I", "title": "X", "items": [_item("Pick a slot", "you")]}]
        )

    @pytest.mark.parametrize(
        ("family", "today", "overnight", "decisions"),
        [
            ("boardingpass", 3, 3, 2),
            ("metromap", 3, 3, 2),
            ("menu", 3, 3, 1),
            ("invoice", 3, 3, 1),
            ("almanac", 2, 0, 1),
            ("broadsheet", 0, 0, 1),
        ],
    )
    def test_family_gets_every_slot_it_reads(
        self, family: str, today: int, overnight: int, decisions: int
    ) -> None:
        content = build_ed(
            self._sparse(),
            edition_no=1,
            generated_local="",
            assets=ASSETS,
            art_credit=CREDIT,
            family=family,
        )["content"]

        counts = (len(content["today"]), len(content["overnight"]), len(content["decisions"]))
        assert counts == (today, overnight, decisions)

    def test_padding_follows_the_real_items_and_reads_as_an_empty_slot(self) -> None:
        content = build_ed(
            self._sparse(),
            edition_no=1,
            generated_local="",
            assets=ASSETS,
            art_credit=CREDIT,
            family="boardingpass",
        )["content"]

        assert [d["label"] for d in content["decisions"]] == ["a slot", "—"]
        assert content["decisions"][1] == {"verb": "", "label": "—", "note": None, "empty": True}
        assert [(r["label"], r["t24"], r.get("empty")) for r in content["today"]] == [
            ("—", None, True)
        ] * 3

    def test_a_full_bucket_is_never_padded(self) -> None:
        payload = _payload(
            calendar=[{"date": "2026-07-05", "start": None, "title": f"n{i}"} for i in range(4)]
        )
        content = build_ed(
            payload,
            edition_no=1,
            generated_local="",
            assets=ASSETS,
            art_credit=CREDIT,
            family="menu",
        )["content"]

        assert [r["label"] for r in content["today"]] == ["n0", "n1", "n2", "n3"]
