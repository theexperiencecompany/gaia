"""Unit tests for the BriefingPayload -> explorer ed adapter.

build_ed is pure, so every test drives the real function and pins the exact ed values
the vendored JS templates read.
"""

from typing import Any

import pytest

from app.models.briefing_models import BriefingPayload
from app.services.briefing.editions.explorer_adapter import ExplorerArt, build_ed
from app.services.briefing.editions.explorer_render import explorer_family_ids
from app.services.briefing.editions.stamps import stamp_for

ASSETS = {"ART1": "data:image/jpeg;base64,AAAA", "BAND": "data:image/webp;base64,BBBB"}
ART: ExplorerArt = {
    "src": "data:image/jpeg;base64,AAAA",
    "title": "Wheat Field with Cypresses",
    "artist": "Vincent van Gogh",
    "year": "1889",
    "medium": "oil on canvas",
}


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
            art=ART,
            family=family,
        )["content"]

        rows = [*content["today"], *content["overnight"], *content["decisions"]]
        labels = [row["label"] for row in rows if row["label"] != "—"]
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
    @pytest.mark.parametrize("family", ["memo", "postal", "broadsheet", "receipt"])
    def test_every_family_leads_with_the_headline(self, family: str) -> None:
        ed = _build(_payload(headline="Two replies need you"), family=family)

        assert ed["deck"] == "Two replies need you"

    def test_an_empty_bucket_is_never_padded_with_a_placeholder_row(self) -> None:
        content = _build(_payload(), family="boardingpass")["content"]

        assert (content["today"], content["overnight"], content["decisions"]) == ([], [], [])


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
class TestOvernightClock:
    def test_a_leading_clock_prefix_becomes_the_rows_24_hour_time(self) -> None:
        overnight = _build(
            _payload(
                sections=[
                    {
                        "numeral": "I",
                        "title": "X",
                        "items": [_item("1:30 PM — Shipped the deck", "lookback")],
                    }
                ]
            )
        )["content"]["overnight"]

        assert overnight == [
            {"t24": "13:30", "label": "Shipped the deck", "note": None, "tag": "DONE"}
        ]


def _asks(*texts: str) -> BriefingPayload:
    return _payload(
        sections=[{"numeral": "I", "title": "X", "items": [_item(t, "you") for t in texts]}]
    )


@pytest.mark.unit
class TestDecisionVerbs:
    def _decisions(self, *texts: str) -> list[dict[str, Any]]:
        return list(_build(_asks(*texts))["content"]["decisions"])

    def test_a_non_imperative_ask_is_offered_for_review_verbatim(self) -> None:
        assert self._decisions("Lunch with Ana") == [
            {"verb": "Review", "label": "Lunch with Ana", "note": None}
        ]

    def test_a_blank_ask_is_offered_for_review_unchanged(self) -> None:
        assert self._decisions("   ") == [{"verb": "Review", "label": "   ", "note": None}]

    def test_punctuation_after_the_verb_is_not_part_of_it(self) -> None:
        assert self._decisions("approve: the budget") == [
            {"verb": "Approve", "label": "the budget", "note": None}
        ]

    def test_a_dash_after_the_verb_is_dropped_from_the_label(self) -> None:
        assert self._decisions("Approve — the budget") == [
            {"verb": "Approve", "label": "the budget", "note": None}
        ]

    def test_the_label_keeps_its_own_leading_letters_and_trailing_dash(self) -> None:
        assert self._decisions("Approve Xavier's expense —") == [
            {"verb": "Approve", "label": "Xavier's expense —", "note": None}
        ]

    def test_a_bare_verb_leaves_an_empty_label(self) -> None:
        assert self._decisions("Confirm") == [{"verb": "Confirm", "label": "", "note": None}]

    def test_a_word_that_merely_contains_a_verb_is_not_one(self) -> None:
        assert self._decisions("SENDX the file") == [
            {"verb": "Review", "label": "SENDX the file", "note": None}
        ]


@pytest.mark.unit
class TestStats:
    def test_figures_come_from_the_tallies(self) -> None:
        ed = _build(_payload(tallies={"done_by_you": 2, "done_by_gaia": 1}))

        assert ed["content"]["stats"] == {
            "done": 3,
            "you": 2,
            "gaia": 1,
            "mail": None,
            "focus": None,
        }

    def test_a_zero_figure_is_unknown_so_the_template_draws_nothing(self) -> None:
        stats = _build(_payload(tallies={"done_by_you": 1, "done_by_gaia": 0}))["content"]["stats"]

        assert (stats["done"], stats["you"], stats["gaia"]) == (1, 1, None)

    def test_work_done_only_by_gaia_still_draws_the_figures(self) -> None:
        stats = _build(_payload(tallies={"done_by_you": 0, "done_by_gaia": 2}))["content"]["stats"]

        assert (stats["done"], stats["you"], stats["gaia"]) == (2, None, 2)

    def test_no_tallies_leaves_no_stats_block(self) -> None:
        assert _build(_payload())["content"]["stats"] is None

    def test_zero_tallies_leave_no_stats_block(self) -> None:
        payload = _payload(tallies={"done_by_you": 0, "done_by_gaia": 0})

        assert _build(payload)["content"]["stats"] is None


@pytest.mark.unit
class TestAwaiting:
    def test_counts_every_todo_behind_the_asks_and_retries(self) -> None:
        section = {
            "numeral": "I",
            "title": "Needs you",
            "items": [
                {"text": "Approve the Acme MSA renewal", "kind": "you", "count": 3},
                _item("Sync Stripe", "failed"),
                _item("Investor update", "lookback"),
            ],
        }

        assert _build(_payload(sections=[section]))["content"]["awaiting"] == 4

    def test_nothing_awaiting_is_unknown_so_the_template_bills_no_figure(self) -> None:
        section = {"numeral": "I", "title": "Work", "items": [_item("Deck", "lookback")]}

        assert _build(_payload(sections=[section]))["content"]["awaiting"] is None


_WEEK = {
    "days": [{"you": i, "gaia": 7 - i} for i in range(7)],
    "shipped": ["Launch post"],
    "handled": ["Inbox zero"],
    "ahead": [{"date": "2026-07-06", "title": "Board meeting"}],
}


@pytest.mark.unit
class TestWeek:
    def test_the_weekly_family_draws_the_real_week(self) -> None:
        ed = _build(_payload(week=_WEEK), family="weekly")

        assert ed["week"] == {
            "days": [{"you": i, "gaia": 7 - i} for i in range(7)],
            "shipped": ["Launch post"],
            "handled": ["Inbox zero"],
            "ahead": [{"day": "Mon", "label": "Board meeting"}],
        }

    def test_the_weekly_family_without_a_week_draws_none(self) -> None:
        assert _build(_payload(), family="weekly")["week"] is None

    def test_other_families_carry_no_week(self) -> None:
        assert _build(_payload(week=_WEEK), family="swiss")["week"] is None


@pytest.mark.unit
class TestStamp:
    def test_air_mail_carries_the_drawn_citys_stamp(self) -> None:
        ed = _build(_payload(stamp_city="paris"), family="postal")

        assert ed["stamp"] == stamp_for("paris")

    def test_a_legacy_air_mail_brief_without_a_city_keeps_the_template_axis(self) -> None:
        assert _build(_payload(), family="postal")["stamp"] is None

    def test_other_families_carry_no_stamp(self) -> None:
        assert _build(_payload(stamp_city="paris"), family="swiss")["stamp"] is None
