"""The brief's skim text — the one short shape every surface leads with."""

from typing import Any

import pytest

from app.models.briefing_models import BriefingPayload
from app.services.briefing.skim import MAX_SKIM_ASKS, build_skim, split_for_caption

_LINK = "https://heygaia.io/briefings"


def _payload(items: list[tuple[str, str]], **overrides: Any) -> BriefingPayload:
    data: dict[str, Any] = {
        "kicker": "K",
        "date": "2026-10-14",
        "headline": "Two replies need you before your 11:00.",
        "lede": "lede",
        "sections": [
            {"numeral": "I", "title": "X", "items": [{"text": t, "kind": k} for t, k in items]}
        ],
        "mood": "packed",
        "caption": "c",
    }
    data.update(overrides)
    return BriefingPayload.model_validate(data)


@pytest.mark.unit
class TestBuildSkim:
    def test_headline_asks_overnight_then_link(self) -> None:
        skim = build_skim(
            _payload(
                [
                    ("Approve the Priya reply", "you"),
                    ("Sync Stripe invoices", "failed"),
                    ("Investor update", "lookback"),
                    ("Q4 hiring plan", "gaia"),
                ]
            ),
            _LINK,
        )

        assert skim.text == (
            "Two replies need you before your 11:00.\n\n"
            "• Approve the Priya reply\n"
            "• Retry: Sync Stripe invoices\n\n"
            "Overnight I finished Investor update; Q4 hiring plan is still in progress.\n\n"
            f"Full brief: {_LINK}"
        )

    def test_at_most_three_asks(self) -> None:
        skim = build_skim(_payload([(f"Ask {i}", "you") for i in range(6)]), _LINK)

        assert skim.asks == [f"Ask {i}" for i in range(MAX_SKIM_ASKS)]

    def test_a_quiet_day_is_the_headline_and_the_link(self) -> None:
        skim = build_skim(_payload([]), _LINK)

        assert skim.text == f"Two replies need you before your 11:00.\n\nFull brief: {_LINK}"
        assert skim.preheader == ""

    @pytest.mark.parametrize(
        ("done", "running", "sentence"),
        [
            (["A"], [], "Overnight I finished A."),
            (["A", "B", "C"], [], "Overnight I finished A, B and 1 more."),
            ([], ["R"], "Overnight R is in progress."),
        ],
    )
    def test_one_overnight_sentence(
        self, done: list[str], running: list[str], sentence: str
    ) -> None:
        items = [(t, "lookback") for t in done] + [(t, "gaia") for t in running]

        assert build_skim(_payload(items), _LINK).overnight == sentence

    def test_the_weekly_recap_speaks_of_the_week(self) -> None:
        skim = build_skim(_payload([("Deck", "lookback")], mood="weekly"), _LINK)

        assert skim.overnight == "This week I finished Deck."

    def test_preheader_is_the_asks_and_overnight_on_one_line(self) -> None:
        skim = build_skim(_payload([("Pick a slot", "you"), ("Deck", "lookback")]), _LINK)

        assert skim.preheader == "Pick a slot · Overnight I finished Deck."


@pytest.mark.unit
class TestSplitForCaption:
    def test_a_short_skim_is_one_caption(self) -> None:
        assert split_for_caption("a\n\nb", limit=1024) == ["a\n\nb"]

    def test_a_long_skim_splits_on_paragraphs_into_follow_ups(self) -> None:
        text = "\n\n".join(["x" * 600, "y" * 600, "z" * 100])

        parts = split_for_caption(text, limit=1024)

        assert parts == ["x" * 600, "y" * 600 + "\n\n" + "z" * 100]
        assert all(len(p) <= 1024 for p in parts)

    def test_a_paragraph_longer_than_the_limit_is_cut_on_words(self) -> None:
        text = " ".join(["word"] * 400)

        parts = split_for_caption(text, limit=100)

        assert all(len(p) <= 100 for p in parts)
        assert " ".join(parts).split() == text.split()
