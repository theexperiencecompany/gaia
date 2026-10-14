"""The brief's skim text — the one short shape every surface leads with."""

from typing import Any

import pytest

from app.models.briefing_models import BriefingPayload
from app.services.briefing.skim import MAX_SKIM_ASKS, build_skim

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
            )
        )

        assert skim.text(_LINK) == (
            "Two replies need you before your 11:00.\n\n"
            "• Approve the Priya reply\n"
            "• Retry: Sync Stripe invoices\n\n"
            "Overnight I finished Investor update; Q4 hiring plan is still in progress.\n\n"
            f"Full brief: {_LINK}"
        )

    def test_at_most_three_asks(self) -> None:
        skim = build_skim(_payload([(f"Ask {i}", "you") for i in range(6)]))

        assert skim.asks == [f"Ask {i}" for i in range(MAX_SKIM_ASKS)]

    def test_a_quiet_day_is_the_headline_and_the_link(self) -> None:
        skim = build_skim(_payload([]))

        assert skim.text(_LINK) == f"Two replies need you before your 11:00.\n\nFull brief: {_LINK}"
        assert skim.preheader == ""

    @pytest.mark.parametrize(
        ("done", "running", "sentence"),
        [
            (["A"], [], "Overnight I finished A."),
            (["A", "B"], [], "Overnight I finished A and B."),
            (["A", "B", "C"], [], "Overnight I finished A, B and 1 more."),
            ([], ["R"], "Overnight R is in progress."),
            ([], ["R", "S"], "Overnight R and S are in progress."),
            (["A"], ["R", "S"], "Overnight I finished A; R and S are still in progress."),
        ],
    )
    def test_one_overnight_sentence(
        self, done: list[str], running: list[str], sentence: str
    ) -> None:
        items = [(t, "lookback") for t in done] + [(t, "gaia") for t in running]

        assert build_skim(_payload(items)).overnight == sentence

    def test_the_weekly_recap_speaks_of_the_week(self) -> None:
        skim = build_skim(_payload([("Deck", "lookback")], mood="weekly"))

        assert skim.overnight == "This week I finished Deck."

    def test_preheader_is_the_asks_and_overnight_on_one_line(self) -> None:
        skim = build_skim(_payload([("Pick a slot", "you"), ("Deck", "lookback")]))

        assert skim.preheader == "Pick a slot · Overnight I finished Deck."
