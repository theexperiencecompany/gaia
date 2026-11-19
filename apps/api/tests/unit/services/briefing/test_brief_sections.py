"""The judge's selection laid out as the brief's sections, and read back for what it kept.

Faked seams: none; the wide event is the real one, captured.
"""

from tests.helpers import captured_wide_event

from app.constants.briefing import BriefAction, BriefOutcome, SectionKey
from app.models.brief_candidate_models import BriefCandidate, CandidateKind
from app.models.briefing_models import BriefingItem
from app.services.briefing.candidates.judge import BriefSelection
from app.services.briefing.sections import chosen_sections, log_selection

TITLES = {
    SectionKey.LEAD: "Lead",
    SectionKey.NEEDS_YOU: "Needs you",
    SectionKey.UPDATES: "Updates",
    SectionKey.GAIA_DID: "GAIA's work",
}


def _candidate(title: str) -> BriefCandidate:
    return BriefCandidate(
        source="gaia", app="GAIA", kind=CandidateKind.NEEDS_YOU, state="you", title=title
    )


def _selection(
    *, dropped: list[int] | None = None, more: dict[SectionKey, int] | None = None
) -> BriefSelection:
    return BriefSelection(
        sections={
            SectionKey.NEEDS_YOU: [1, 2],
            SectionKey.UPDATES: [3],
            SectionKey.GAIA_DID: [4],
        },
        items={
            1: BriefingItem(text="Approve the reply", action=BriefAction.APPROVE),
            2: BriefingItem(text="Review the deck", action=BriefAction.REVIEW),
            3: BriefingItem(text="Payout landed", outcome=BriefOutcome.FINISHED),
            4: BriefingItem(text="Investor update", outcome=BriefOutcome.FINISHED),
        },
        offer=None,
        dropped=[5, 6] if dropped is None else dropped,
        more={SectionKey.NEEDS_YOU: 3} if more is None else more,
    )


class TestChosenSections:
    def test_sections_come_in_reading_order_numbered_with_their_items_and_overflow(self) -> None:
        pool = {i: _candidate(f"candidate {i}") for i in range(1, 5)}

        chosen = chosen_sections(_selection(), pool, TITLES)

        assert [
            (s.numeral, s.title, s.key, [i.text for i in s.items], s.more) for s in chosen.sections
        ] == [
            ("I", "Needs you", SectionKey.NEEDS_YOU, ["Approve the reply", "Review the deck"], 3),
            ("II", "Updates", SectionKey.UPDATES, ["Payout landed"], 0),
            ("III", "GAIA's work", SectionKey.GAIA_DID, ["Investor update"], 0),
        ]
        assert [[(i, c.title) for i, c in picked] for picked in chosen.picked] == [
            [(1, "candidate 1"), (2, "candidate 2")],
            [(3, "candidate 3")],
            [(4, "candidate 4")],
        ]


class TestLogSelection:
    async def test_the_wide_event_carries_what_was_kept_dropped_and_left_over(self) -> None:
        async with captured_wide_event() as event:
            log_selection(7, _selection())

        assert event["brief_selection"] == {
            "candidates": 7,
            "kept": {"needs_you": 2, "updates": 1, "gaia_did": 1},
            "dropped": 2,
            "more": {"needs_you": 3},
        }
