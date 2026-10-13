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
class TestBucketingByPosition:
    def test_first_three_sections_map_to_today_overnight_decisions(self) -> None:
        ed = _build(
            _payload(
                sections=[
                    {"numeral": "I", "title": "Today", "items": [_item("Standup at nine")]},
                    {"numeral": "II", "title": "Overnight", "items": [_item("Drafted the memo")]},
                    {"numeral": "III", "title": "Decisions", "items": [_item("Approve the SOW")]},
                ]
            )
        )
        content = ed["content"]

        assert [row["label"] for row in content["today"]] == ["Standup at nine"]
        assert [row["label"] for row in content["overnight"]] == ["Drafted the memo"]
        assert content["decisions"] == [
            {"verb": "Approve", "label": "the SOW", "note": None},
        ]

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

    def test_a_section_with_no_items_still_leaves_its_bucket_placeheld(self) -> None:
        content = _build(
            _payload(
                sections=[
                    {"numeral": "I", "title": "Today", "items": []},
                    {"numeral": "II", "title": "Overnight", "items": [_item("Filed the report")]},
                ]
            )
        )["content"]

        assert content["today"][0]["label"] == "Nothing on the calendar today"
        assert [row["label"] for row in content["overnight"]] == ["Filed the report"]

    def test_items_within_a_section_keep_their_order(self) -> None:
        content = _build(
            _payload(
                sections=[
                    {
                        "numeral": "I",
                        "title": "Today",
                        "items": [_item("first"), _item("second"), _item("third")],
                    }
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
            ("note", "today"),
            ("something-new", "today"),
        ],
    )
    def test_fourth_section_items_fold_into_a_bucket_by_kind(self, kind: str, bucket: str) -> None:
        content = _build(
            _payload(
                sections=[
                    {"numeral": "I", "title": "Today", "items": [_item("anchor today")]},
                    {"numeral": "II", "title": "Overnight", "items": [_item("anchor overnight")]},
                    {"numeral": "III", "title": "Decisions", "items": [_item("anchor decision")]},
                    {"numeral": "IV", "title": "Extra", "items": [_item("folded", kind)]},
                ]
            )
        )["content"]

        labels = {
            name: [row["label"] for row in content[name]] for name in content if name != "stats"
        }
        assert "folded" in labels[bucket]
        for name, values in labels.items():
            if name != bucket:
                assert "folded" not in values

    def test_fifth_section_folds_too_and_lands_after_the_fourth(self) -> None:
        content = _build(
            _payload(
                sections=[
                    {"numeral": "I", "title": "Today", "items": []},
                    {"numeral": "II", "title": "Overnight", "items": []},
                    {"numeral": "III", "title": "Decisions", "items": []},
                    {"numeral": "IV", "title": "Extra", "items": [_item("fourth", "gaia")]},
                    {"numeral": "V", "title": "More", "items": [_item("fifth", "lookback")]},
                ]
            )
        )["content"]

        assert [row["label"] for row in content["overnight"]] == ["fourth", "fifth"]


@pytest.mark.unit
class TestItemMapping:
    @pytest.mark.parametrize(
        ("kind", "tag"),
        [
            ("proposal", "APPROVAL"),
            ("you", "YOUR MOVE"),
            ("needs_you", "YOUR MOVE"),
            ("gaia", "DONE"),
            ("lookback", "DONE"),
            ("note", ""),
            ("unknown-kind", ""),
        ],
    )
    def test_kind_condenses_to_the_templates_caps_tag(self, kind: str, tag: str) -> None:
        content = _build(
            _payload(
                sections=[{"numeral": "I", "title": "Today", "items": [_item("a thing", kind)]}]
            )
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
                    {
                        "numeral": "I",
                        "title": "Today",
                        "items": [_item("1:30 PM — Sync with Ana")],
                    }
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
            _payload(
                sections=[
                    {"numeral": "I", "title": "Today", "items": []},
                    {"numeral": "II", "title": "Overnight", "items": [{"kind": "gaia"}]},
                ]
            )
        )["content"]

        assert content["overnight"][0] == {
            "t24": None,
            "label": "",
            "note": None,
            "tag": "DONE",
        }

    @pytest.mark.parametrize(
        ("kind", "tag"),
        [
            ("gaia", "DONE"),
            ("lookback", "DONE"),
            ("proposal", "APPROVAL"),
            ("note", ""),
            ("unknown-kind", ""),
        ],
    )
    def test_overnight_kind_condenses_to_the_templates_caps_tag(self, kind: str, tag: str) -> None:
        content = _build(
            _payload(
                sections=[
                    {"numeral": "I", "title": "Today", "items": []},
                    {
                        "numeral": "II",
                        "title": "Overnight",
                        "items": [_item("a thing", kind)],
                    },
                ]
            )
        )["content"]

        assert content["overnight"][0]["tag"] == tag

    def test_overnight_rows_keep_t24_but_carry_no_display_time_field(self) -> None:
        content = _build(
            _payload(
                sections=[
                    {"numeral": "I", "title": "Today", "items": []},
                    {
                        "numeral": "II",
                        "title": "Overnight",
                        "items": [_item("2:15 AM — Rebuilt the index", "gaia")],
                    },
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
                    {"numeral": "III", "title": "Decisions", "items": [_item(text)]},
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
