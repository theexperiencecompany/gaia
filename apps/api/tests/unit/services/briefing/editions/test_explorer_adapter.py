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

    def test_deck_is_the_payload_lede(self) -> None:
        ed = _build(_payload(lede="Quiet morning."))

        assert ed["deck"] == "Quiet morning."

    def test_non_string_lede_is_coerced_rather_than_raising(self) -> None:
        ed = _build(_payload(lede=7))

        assert ed["deck"] == "7"

    def test_absent_lede_key_becomes_an_empty_deck(self) -> None:
        ed = _build({"date": "2026-07-05"})

        assert ed["deck"] == ""

    def test_text_is_not_pre_escaped_because_templates_escape_their_own(self) -> None:
        ed = _build(_payload(lede="Ana & Bo <b>ship</b>"))

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
class TestBucketingByKind:
    """Items land in a bucket by what they are, not by which section they sat in.

    The daily brief's code-built sections are NEEDS YOU then GAIA'S WORK, so
    positional bucketing put the user's asks under "today", GAIA's running work
    under "overnight" with a DONE tag, and left "decisions" on its "Nothing
    pending your review" placeholder while two items waited on the user.
    """

    def test_the_daily_brief_shape_lands_every_item_where_it_belongs(self) -> None:
        content = _build(
            _payload(
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
                ]
            )
        )["content"]

        assert content["decisions"] == [
            {"verb": "Approve", "label": "the Priya reply", "note": None}
        ]
        assert [(r["label"], r["tag"]) for r in content["today"]] == [
            ("Sync Stripe invoices", "FAILED")
        ]
        assert [(r["label"], r["tag"]) for r in content["overnight"]] == [
            ("Investor update", "DONE"),
            ("Q4 hiring plan", "IN PROGRESS"),
        ]

    def test_review_placeholder_shows_only_when_nothing_waits_on_the_user(self) -> None:
        waiting = _build(
            _payload(
                sections=[{"numeral": "I", "title": "X", "items": [_item("Pick a slot", "you")]}]
            )
        )["content"]["decisions"]
        nothing = _build(
            _payload(
                sections=[{"numeral": "I", "title": "X", "items": [_item("Done", "lookback")]}]
            )
        )["content"]["decisions"]

        assert all(row["label"] != "Nothing pending your review" for row in waiting)
        assert nothing == [{"verb": "Review", "label": "Nothing pending your review", "note": None}]

    def test_every_bucket_gets_an_honest_placeholder_when_empty(self) -> None:
        content = _build(_payload())["content"]

        assert content["today"] == [
            {
                "time": None,
                "t24": None,
                "label": "Nothing on the calendar today",
                "note": None,
                "tag": "",
            }
        ]
        assert content["overnight"] == [
            {"t24": None, "label": "Nothing to report from overnight", "note": None, "tag": ""}
        ]
        assert content["decisions"] == [
            {"verb": "Review", "label": "Nothing pending your review", "note": None}
        ]

    def test_items_keep_their_order_across_sections(self) -> None:
        content = _build(
            _payload(
                sections=[
                    {"numeral": "I", "title": "A", "items": [_item("first"), _item("second")]},
                    {"numeral": "II", "title": "B", "items": [_item("third")]},
                ]
            )
        )["content"]

        assert [row["label"] for row in content["today"]] == ["first", "second", "third"]

    @pytest.mark.parametrize(
        ("kind", "bucket"),
        [
            ("gaia", "overnight"),
            ("lookback", "overnight"),
            ("you", "decisions"),
            ("needs_you", "decisions"),
            ("proposal", "decisions"),
            ("failed", "today"),
            ("note", "today"),
            ("something-new", "today"),
        ],
    )
    @pytest.mark.parametrize("position", [0, 1, 2, 3])
    def test_bucket_follows_kind_in_any_section(
        self, kind: str, bucket: str, position: int
    ) -> None:
        sections = [{"numeral": str(i), "title": "S", "items": []} for i in range(4)]
        sections[position]["items"] = [_item("placed", kind)]
        content = _build(_payload(sections=sections))["content"]

        labels = {
            name: [row["label"] for row in content[name]] for name in content if name != "stats"
        }
        assert "placed" in labels[bucket]
        assert all("placed" not in v for name, v in labels.items() if name != bucket)


@pytest.mark.unit
class TestItemMapping:
    @pytest.mark.parametrize(
        ("kind", "tag"),
        [
            ("failed", "FAILED"),
            ("note", ""),
            ("unknown-kind", ""),
        ],
    )
    def test_today_kind_condenses_to_the_templates_caps_tag(self, kind: str, tag: str) -> None:
        content = _build(
            _payload(sections=[{"numeral": "I", "title": "T", "items": [_item("a thing", kind)]}])
        )["content"]

        assert content["today"][0]["tag"] == tag

    def test_item_with_no_kind_defaults_to_note(self) -> None:
        content = _build(
            _payload(sections=[{"numeral": "I", "title": "Today", "items": [{"text": "bare"}]}])
        )["content"]

        assert content["today"][0] == {
            "time": None,
            "t24": None,
            "label": "bare",
            "note": None,
            "tag": "",
        }

    def test_item_with_no_text_becomes_an_empty_label(self) -> None:
        content = _build(
            _payload(sections=[{"numeral": "I", "title": "Today", "items": [{"kind": "note"}]}])
        )["content"]

        assert content["today"][0]["label"] == ""

    def test_clock_prefix_is_lifted_out_of_the_today_label(self) -> None:
        content = _build(
            _payload(
                sections=[
                    {"numeral": "I", "title": "Today", "items": [_item("1:30 PM — Sync with Ana")]}
                ]
            )
        )["content"]

        assert content["today"][0]["time"] == "1:30 PM"
        assert content["today"][0]["t24"] == "13:30"
        assert content["today"][0]["label"] == "Sync with Ana"

    @pytest.mark.parametrize("separator", ["-", "–", "—"])
    def test_hyphen_en_dash_and_em_dash_all_separate_the_clock_prefix(self, separator: str) -> None:
        content = _build(
            _payload(
                sections=[
                    {
                        "numeral": "I",
                        "title": "Today",
                        "items": [_item(f"9:00 AM {separator} Standup")],
                    }
                ]
            )
        )["content"]

        assert content["today"][0]["time"] == "9:00 AM"
        assert content["today"][0]["label"] == "Standup"

    def test_text_without_a_clock_prefix_keeps_the_whole_label(self) -> None:
        content = _build(
            _payload(
                sections=[
                    {"numeral": "I", "title": "Today", "items": [_item("Lunch with the team")]}
                ]
            )
        )["content"]

        assert content["today"][0]["time"] is None
        assert content["today"][0]["t24"] is None
        assert content["today"][0]["label"] == "Lunch with the team"

    def test_overnight_item_with_no_text_becomes_an_empty_label(self) -> None:
        content = _build(
            _payload(sections=[{"numeral": "I", "title": "W", "items": [{"kind": "lookback"}]}])
        )["content"]

        assert content["overnight"][0] == {"t24": None, "label": "", "note": None, "tag": "DONE"}

    @pytest.mark.parametrize(("kind", "tag"), [("gaia", "IN PROGRESS"), ("lookback", "DONE")])
    def test_overnight_kind_condenses_to_the_templates_caps_tag(self, kind: str, tag: str) -> None:
        content = _build(
            _payload(sections=[{"numeral": "I", "title": "W", "items": [_item("a thing", kind)]}])
        )["content"]

        assert content["overnight"][0]["tag"] == tag

    def test_overnight_rows_keep_t24_but_carry_no_display_time_field(self) -> None:
        content = _build(
            _payload(
                sections=[
                    {
                        "numeral": "I",
                        "title": "W",
                        "items": [_item("2:15 AM — Rebuilt the index", "lookback")],
                    }
                ]
            )
        )["content"]

        assert content["overnight"][0] == {
            "t24": "02:15",
            "label": "Rebuilt the index",
            "note": None,
            "tag": "DONE",
        }


@pytest.mark.unit
class TestDecisionVerbs:
    @pytest.mark.parametrize(
        ("text", "verb", "label"),
        [
            ("Approve the vendor contract", "Approve", "the vendor contract"),
            ("decide on the venue", "Decide", "on the venue"),
            ("REVIEW the pull request", "Review", "the pull request"),
            ("Approve: the renewal", "Approve", "the renewal"),
            ("Send — the invoice", "Send", "the invoice"),
            ("Approve", "Approve", ""),
            ("Ponder the roadmap", "Review", "Ponder the roadmap"),
            ("ApproveX the SOW", "Review", "ApproveX the SOW"),
            ("Approve X-ray budget", "Approve", "X-ray budget"),
            ("", "Review", ""),
            ("   ", "Review", "   "),
        ],
    )
    def test_leading_imperative_becomes_the_verb(self, text: str, verb: str, label: str) -> None:
        content = _build(
            _payload(
                sections=[
                    {"numeral": "I", "title": "Today", "items": []},
                    {"numeral": "II", "title": "Overnight", "items": []},
                    {"numeral": "III", "title": "Decisions", "items": [_item(text, "you")]},
                ]
            )
        )["content"]

        assert content["decisions"][0] == {"verb": verb, "label": label, "note": None}

    def test_decision_item_with_no_text_becomes_an_empty_label(self) -> None:
        content = _build(
            _payload(
                sections=[
                    {"numeral": "I", "title": "Today", "items": []},
                    {"numeral": "II", "title": "Overnight", "items": []},
                    {"numeral": "III", "title": "Decisions", "items": [{"kind": "you"}]},
                ]
            )
        )["content"]

        assert content["decisions"][0] == {"verb": "Review", "label": "", "note": None}


@pytest.mark.unit
class TestStats:
    def test_labels_are_matched_by_keyword_and_coerced_to_ints(self) -> None:
        content = _build(
            _payload(
                stats=[
                    {"value": "7", "label": "Done overnight"},
                    {"value": "3", "label": "Waiting on you"},
                    {"value": "12", "label": "GAIA runs"},
                    {"value": "41", "label": "Unread mail"},
                    {"value": "4h 20m", "label": "Focus time"},
                ]
            )
        )["content"]

        assert content["stats"] == {"done": 7, "you": 3, "gaia": 12, "mail": 41, "focus": "4h 20m"}

    def test_an_email_label_counts_as_the_mail_stat(self) -> None:
        content = _build(_payload(stats=[{"value": "9", "label": "Email triaged"}]))["content"]

        assert content["stats"]["mail"] == 9

    def test_missing_stats_fall_back_to_zero_and_zero_hours(self) -> None:
        content = _build(_payload(stats=[]))["content"]

        assert content["stats"] == {"done": 0, "you": 0, "gaia": 0, "mail": 0, "focus": "0h"}

    def test_non_numeric_value_counts_as_zero_rather_than_raising(self) -> None:
        content = _build(_payload(stats=[{"value": "many", "label": "done"}]))["content"]

        assert content["stats"]["done"] == 0

    def test_whitespace_padded_numbers_are_parsed(self) -> None:
        content = _build(_payload(stats=[{"value": "  8  ", "label": "done"}]))["content"]

        assert content["stats"]["done"] == 8

    def test_first_matching_label_wins(self) -> None:
        content = _build(
            _payload(
                stats=[
                    {"value": "1", "label": "done today"},
                    {"value": "99", "label": "done this week"},
                ]
            )
        )["content"]

        assert content["stats"]["done"] == 1

    def test_focus_value_zero_is_kept_rather_than_replaced_by_the_default(self) -> None:
        content = _build(_payload(stats=[{"value": "0", "label": "Focus"}]))["content"]

        assert content["stats"]["focus"] == "0"

    def test_stat_without_a_value_key_reads_as_zero(self) -> None:
        content = _build(_payload(stats=[{"label": "done"}]))["content"]

        assert content["stats"]["done"] == 0


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
            ("weekly", 3, 1, 1),
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
        assert [r["label"] for r in content["today"]] == [
            "Nothing on the calendar today",
            "—",
            "—",
        ]

    def test_a_full_bucket_is_never_padded(self) -> None:
        payload = _payload(
            sections=[{"numeral": "I", "title": "X", "items": [_item(f"n{i}") for i in range(4)]}]
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
