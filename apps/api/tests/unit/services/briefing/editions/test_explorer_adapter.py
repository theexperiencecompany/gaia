"""Unit tests for the ``BriefingPayload`` -> explorer ``ed`` adapter.

``build_ed`` is pure, so every test drives the real function with a real
payload dict and pins the exact ``ed`` values the vendored JS templates read.
"""

from typing import Any

import pytest

from app.services.briefing.editions.explorer_adapter import build_ed

ASSETS = {"ART1": "data:image/jpeg;base64,AAAA", "BAND": "data:image/webp;base64,BBBB"}
CREDIT = "Wheat Field with Cypresses — Vincent van Gogh"


def _item(text: str, kind: str = "note") -> dict[str, Any]:
    return {"text": text, "kind": kind}


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "date": "2026-07-05",
        "lede": "Three things need you before noon.",
        "stats": [],
        "sections": [],
    }
    payload.update(overrides)
    return payload


def _build(payload: dict[str, Any], *, generated_local: str = "6:02 AM") -> dict[str, Any]:
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

    def test_missing_date_key_degrades_without_raising(self) -> None:
        ed = _build({"lede": "x"})

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

    def test_non_string_lede_is_coerced_rather_than_raising(self) -> None:
        ed = _build(_payload(headline=7))

        assert ed["deck"] == "7"

    def test_absent_lede_key_becomes_an_empty_deck(self) -> None:
        ed = _build({"date": "2026-07-05"})

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

    def _daily(self, **overrides: Any) -> dict[str, Any]:
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

    def test_today_is_the_first_ask_then_the_calendar(self) -> None:
        today = _build(self._daily())["content"]["today"]

        assert today == [
            {"time": None, "t24": None, "label": "the Priya reply", "note": None, "tag": "APPROVE"},
            {
                "time": "11:00 AM",
                "t24": "11:00",
                "label": "Sequoia",
                "note": "Menlo Park",
                "tag": "",
            },
            {"time": None, "t24": None, "label": "Offsite", "note": None, "tag": ""},
        ]

    def test_no_status_word_ever_reaches_a_today_tag(self) -> None:
        today = _build(self._daily())["content"]["today"]

        assert {row["tag"] for row in today} <= {"APPROVE", ""}

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

    def test_with_no_ask_the_next_calendar_event_leads(self) -> None:
        payload = self._daily()
        payload["sections"] = []

        assert _build(payload)["content"]["today"][0]["label"] == "Sequoia"

    def test_review_placeholder_shows_only_when_nothing_waits_on_the_user(self) -> None:
        nothing = _build(_payload(sections=[]))["content"]["decisions"]
        waiting = _build(self._daily())["content"]["decisions"]

        assert nothing == [{"verb": "Review", "label": "Nothing pending your review", "note": None}]
        assert all(row["label"] != "Nothing pending your review" for row in waiting)

    def test_an_empty_day_gets_honest_placeholders(self) -> None:
        content = _build(_payload())["content"]

        assert [r["label"] for r in content["today"]] == ["Nothing on the calendar today"]
        assert [r["label"] for r in content["overnight"]] == ["Nothing to report from overnight"]

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
    """Some vendored families index fixed item slots (the founder fixture always
    held three today, three overnight and two decision items). A family handed
    fewer threw in the page script, and Chromium shipped a blank 2px PNG."""

    def _sparse(self) -> dict[str, Any]:
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
            ("almanac", 2, 1, 1),
            ("broadsheet", 1, 1, 1),
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
        assert [r["label"] for r in content["today"]] == ["a slot", "—", "—"]

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
