"""The selection judge: one call over every candidate, held by code to its ids and section caps.

The model call (ainvoke_structured) is the only faked seam.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from tests.factories import make_user_id

from app.constants.briefing import BRIEF_SELECTION_LABEL, SECTION_CAPS, SectionKey
from app.models.brief_candidate_models import BriefCandidate, CandidateKind
from app.models.briefing_models import BriefingItemKind
from app.models.scout_models import SignalImportance
from app.services.briefing.candidates import judge
from app.services.briefing.candidates.judge import (
    BriefSelectionAnswer,
    checked_selection,
    select_candidates,
)
from app.utils.errors import AppError

USER_ID = make_user_id()
NOW = datetime(2026, 11, 10, 2, 30, tzinfo=UTC)


def _candidate(
    title: str,
    kind: CandidateKind,
    *,
    app: str = "GAIA",
    state: BriefingItemKind = "you",
    importance: SignalImportance = SignalImportance.NORMAL,
) -> BriefCandidate:
    return BriefCandidate(
        source=app.lower(), app=app, kind=kind, state=state, title=title, importance=importance
    )


POOL = {
    1: _candidate(
        "Neha: can you send pricing for a 40 person team?",
        CandidateKind.NEEDS_YOU,
        app="PumpGTM",
        importance=SignalImportance.HIGH,
    ),
    2: _candidate("Gym", CandidateKind.NEEDS_YOU, app="Todoist"),
    3: _candidate("Approve sending the Acme invoice", CandidateKind.NEEDS_YOU),
    4: _candidate("Deploy to staging failed", CandidateKind.NEEDS_YOU, state="failed"),
    5: _candidate("PR #412 merged", CandidateKind.UPDATE, app="GitHub"),
    6: _candidate("Investor update", CandidateKind.GAIA_DID, state="lookback"),
    7: _candidate("Sequoia", CandidateKind.EVENT, app="Google Calendar", state="note"),
}


def _answer(**fields: object) -> BriefSelectionAnswer:
    defaults: dict[str, object] = {
        "lead": 1,
        "offer": "Draft the pricing reply to Neha",
        "needs_you": [3, 4],
        "updates": [5],
        "gaia_did": [6],
        "dropped": [2],
    }
    return BriefSelectionAnswer.model_validate({**defaults, **fields})


class TestTheContract:
    def test_a_valid_answer_becomes_sections_in_its_own_order(self) -> None:
        selection = checked_selection(_answer(needs_you=[4, 3]), POOL)

        assert selection.sections == {
            SectionKey.LEAD: [1],
            SectionKey.NEEDS_YOU: [4, 3],
            SectionKey.UPDATES: [5],
            SectionKey.GAIA_DID: [6],
        }
        assert (selection.offer, selection.dropped, selection.capped) == (
            "Draft the pricing reply to Neha",
            [2],
            [],
        )

    def test_an_event_may_lead_and_may_go_unmentioned(self) -> None:
        selection = checked_selection(
            _answer(lead=7, offer="Pull the Sequoia notes together", needs_you=[1, 3, 4]), POOL
        )

        assert selection.sections[SectionKey.LEAD] == [7]

    def test_a_section_past_its_cap_keeps_its_first_items(self) -> None:
        cap = SECTION_CAPS[SectionKey.NEEDS_YOU]
        pool = {i: _candidate(f"Reply to person {i}", CandidateKind.NEEDS_YOU) for i in range(1, 8)}

        selection = checked_selection(
            _answer(
                lead=None,
                offer=None,
                needs_you=list(range(1, 8)),
                updates=[],
                gaia_did=[],
                dropped=[],
            ),
            pool,
        )

        assert selection.sections == {SectionKey.NEEDS_YOU: list(range(1, cap + 1))}
        assert selection.capped == list(range(cap + 1, 8))

    @pytest.mark.parametrize(
        ("fields", "problem"),
        [
            ({"needs_you": [3, 4, 99]}, "unknown id(s) [99]"),
            ({"needs_you": [3, 4, 6]}, "id(s) [6] placed more than once"),
            ({"updates": [5, 7]}, "event id(s) [7] filed outside the lead"),
            ({"dropped": []}, "id(s) [2] not placed in any list"),
            ({"offer": "  "}, "a lead with no offer"),
            ({"lead": None, "needs_you": [1, 3, 4]}, "an offer with no lead"),
        ],
    )
    def test_an_answer_that_breaks_the_contract_is_rejected(
        self, fields: dict[str, object], problem: str
    ) -> None:
        with pytest.raises(AppError) as raised:
            checked_selection(_answer(**fields), POOL)

        assert raised.value.why == problem


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    answer = AsyncMock(return_value=_answer())
    monkeypatch.setattr(judge, "ainvoke_structured", answer)
    return answer


class TestTheCall:
    async def test_one_call_sees_every_candidate_and_each_apps_criteria(
        self, model: AsyncMock
    ) -> None:
        criteria = {"PumpGTM": "replies from leads that wait on the user's decision"}

        selection = await select_candidates(USER_ID, POOL, criteria, NOW, "Asia/Kolkata")

        assert selection.sections[SectionKey.LEAD] == [1]
        model.assert_awaited_once()
        prompt = model.await_args.args[1]
        assert "- PumpGTM: replies from leads that wait on the user's decision" in prompt
        assert "1. [PumpGTM] needs_you, important: Neha: can you send pricing" in prompt
        assert "7. [Google Calendar] event: Sequoia" in prompt
        assert model.await_args.kwargs["label"] == BRIEF_SELECTION_LABEL

    async def test_a_rejected_answer_is_asked_again_once_with_the_problem_named(
        self, model: AsyncMock
    ) -> None:
        model.side_effect = [_answer(needs_you=[3, 4, 99]), _answer()]

        selection = await select_candidates(USER_ID, POOL, {}, NOW, "UTC")

        assert selection.sections[SectionKey.NEEDS_YOU] == [3, 4]
        retry_prompt = model.await_args_list[1].args[1]
        assert "Your last answer was rejected: unknown id(s) [99]" in retry_prompt

    async def test_an_answer_rejected_twice_fails_the_brief(self, model: AsyncMock) -> None:
        model.return_value = _answer(dropped=[])

        with pytest.raises(AppError, match="selection judge broke its contract"):
            await select_candidates(USER_ID, POOL, {}, NOW, "UTC")

        assert model.await_count == 2

    async def test_a_day_with_only_the_calendar_makes_no_call(self, model: AsyncMock) -> None:
        selection = await select_candidates(USER_ID, {7: POOL[7]}, {}, NOW, "UTC")

        assert selection.sections == {}
        model.assert_not_awaited()
