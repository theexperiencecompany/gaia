"""The selection judge: one call over every candidate, held by code to its ids and section caps.

The model call (ainvoke_structured) is the only faked seam.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from tests.factories import make_user_id
from tests.helpers import captured_wide_event

from app.constants.briefing import (
    BRIEF_ITEM_DETAIL_MAX_CHARS,
    BRIEF_ITEM_TITLE_MAX_CHARS,
    BRIEF_SELECTION_LABEL,
    BRIEFING_KIND_DAILY,
    BRIEFING_KIND_WEEKLY,
    SECTION_CAPS,
    BriefAction,
    BriefOutcome,
    SectionKey,
)
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
    action: BriefAction | None = None,
) -> BriefCandidate:
    return BriefCandidate(
        source=app.lower(),
        app=app,
        kind=kind,
        state=state,
        title=title,
        importance=importance,
        action=action,
    )


POOL = {
    1: _candidate(
        "Neha: can you send pricing for a 40 person team?",
        CandidateKind.NEEDS_YOU,
        app="PumpGTM",
        importance=SignalImportance.HIGH,
    ),
    2: _candidate("Gym", CandidateKind.NEEDS_YOU, app="Todoist"),
    3: _candidate(
        "Approve sending the Acme invoice", CandidateKind.NEEDS_YOU, action=BriefAction.APPROVE
    ),
    4: _candidate("Deploy to staging failed", CandidateKind.NEEDS_YOU, state="failed"),
    5: _candidate("PR #412 merged", CandidateKind.UPDATE, app="GitHub"),
    6: _candidate("Investor update", CandidateKind.GAIA_DID, state="lookback"),
    7: _candidate("Sequoia", CandidateKind.EVENT, app="Google Calendar", state="note"),
}


# How the judge words each candidate it keeps: the section decides action or outcome.
_WORDING: dict[int, dict[str, object]] = {
    1: {"action": "reply", "title": "Neha's pricing question", "detail": "40 person team"},
    3: {"action": "review", "title": "Acme invoice"},
    4: {"action": "retry", "title": "Staging deploy", "detail": "failed overnight"},
    5: {"outcome": "landed", "title": "PR #412"},
    6: {"outcome": "finished", "title": "Investor update"},
    7: {"action": "attend", "title": "Sequoia"},
}


def _chosen(candidate_id: int) -> dict[str, object]:
    return {"id": candidate_id, **_WORDING.get(candidate_id, {"title": f"Item {candidate_id}"})}


def _answer(**fields: object) -> BriefSelectionAnswer:
    """Build an answer from ids; a lead or list given as ids is worded from _WORDING."""
    defaults: dict[str, object] = {
        "lead": 1,
        "offer": "Draft the pricing reply to Neha",
        "needs_you": [3, 4],
        "updates": [5],
        "gaia_did": [6],
        "dropped": [2],
    }
    merged = {**defaults, **fields}
    worded = {
        key: [_chosen(i) if isinstance(i, int) else i for i in entries]
        for key in ("needs_you", "updates", "gaia_did")
        if isinstance(entries := merged[key], list)
    }
    lead = merged["lead"]
    return BriefSelectionAnswer.model_validate(
        {**merged, **worded, "lead": _chosen(lead) if isinstance(lead, int) else lead}
    )


class TestTheContract:
    def test_a_valid_answer_becomes_sections_in_its_own_order(self) -> None:
        selection = checked_selection(_answer(needs_you=[4, 3]), POOL)

        assert selection.sections == {
            SectionKey.LEAD: [1],
            SectionKey.NEEDS_YOU: [4, 3],
            SectionKey.UPDATES: [5],
            SectionKey.GAIA_DID: [6],
        }
        assert (selection.offer, selection.dropped, selection.more) == (
            "Draft the pricing reply to Neha",
            [2],
            {},
        )

    def test_each_kept_item_carries_the_judges_wording_and_its_sections_contract(self) -> None:
        selection = checked_selection(_answer(), POOL)

        assert [
            (i, item.text, item.detail, item.action, item.outcome)
            for i, item in selection.items.items()
        ] == [
            (1, "Neha's pricing question", "40 person team", BriefAction.REPLY, None),
            (3, "Acme invoice", None, BriefAction.APPROVE, None),
            (4, "Staging deploy", "failed overnight", BriefAction.RETRY, None),
            (5, "PR #412", None, None, BriefOutcome.LANDED),
            (6, "Investor update", None, None, BriefOutcome.FINISHED),
        ]
        assert selection.items[1].offer == "Draft the pricing reply to Neha"

    def test_the_lead_is_never_also_filed_in_a_section(self) -> None:
        selection = checked_selection(_answer(needs_you=[1, 3, 4]), POOL)

        assert selection.sections[SectionKey.LEAD] == [1]
        assert selection.sections[SectionKey.NEEDS_YOU] == [3, 4]
        assert selection.items[1].offer == "Draft the pricing reply to Neha"

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
                needs_you=[
                    {"id": i, "action": "reply", "title": f"Person {i}"} for i in range(1, 8)
                ],
                updates=[],
                gaia_did=[],
                dropped=[],
            ),
            pool,
        )

        assert selection.sections == {SectionKey.NEEDS_YOU: list(range(1, cap + 1))}
        assert selection.more == {SectionKey.NEEDS_YOU: 7 - cap}
        assert set(selection.items) == set(range(1, cap + 1))

    @pytest.mark.parametrize(
        ("fields", "problem"),
        [
            ({"needs_you": [3, 4, 99]}, "unknown id(s) [99]"),
            ({"needs_you": [3, 4, 6]}, "id(s) [6] placed more than once"),
            ({"updates": [5, 7]}, "event id(s) [7] filed outside the lead"),
            ({"dropped": []}, "id(s) [2] not placed in any list"),
            ({"offer": "  "}, "a lead with no offer"),
            ({"lead": None, "needs_you": [1, 3, 4]}, "an offer with no lead"),
            (
                {"updates": [{"id": 5, "title": "PR #412"}]},
                "id 5 in updates: no outcome",
            ),
            (
                {"needs_you": [3, {"id": 4, "title": "Staging deploy"}]},
                "id 4 in needs_you: no action",
            ),
            (
                {
                    "updates": [{"id": 5, "title": "PR #412"}],
                    "gaia_did": [{"id": 6, "title": "Investor update"}],
                },
                "id 5 in updates: no outcome; id 6 in gaia_did: no outcome",
            ),
            (
                {"gaia_did": [{"id": 6, "outcome": "finished", "title": "x" * 51}]},
                "id 6 in gaia_did: a title of 51 characters, not 1 to 50",
            ),
            (
                {
                    "gaia_did": [
                        {"id": 6, "outcome": "finished", "title": "Deck", "detail": "y" * 81}
                    ]
                },
                "id 6 in gaia_did: a detail of 81 characters, over 80",
            ),
        ],
    )
    def test_an_answer_that_breaks_the_contract_is_rejected(
        self, fields: dict[str, object], problem: str
    ) -> None:
        with pytest.raises(AppError) as raised:
            checked_selection(_answer(**fields), POOL)

        assert raised.value.why == problem

    def test_a_rejection_names_the_contract_how_it_recovers_and_the_answer_it_refused(
        self,
    ) -> None:
        answer = _answer(needs_you=[3, 4, 99])

        with pytest.raises(AppError) as raised:
            checked_selection(answer, POOL)

        assert raised.value.message == "the brief's selection judge broke its contract"
        assert raised.value.fix == (
            "the judge was asked again once with the problem named; "
            "the next scheduled brief retries"
        )
        assert raised.value.meta == {"answer": answer.model_dump()}

    def test_a_title_and_a_detail_at_their_limits_are_kept_as_written(self) -> None:
        title, detail = "t" * BRIEF_ITEM_TITLE_MAX_CHARS, "d" * BRIEF_ITEM_DETAIL_MAX_CHARS

        selection = checked_selection(
            _answer(gaia_did=[{"id": 6, "outcome": "finished", "title": title, "detail": detail}]),
            POOL,
        )

        assert (selection.items[6].text, selection.items[6].detail) == (title, detail)

    def test_a_blank_detail_is_no_detail(self) -> None:
        selection = checked_selection(
            _answer(gaia_did=[{"id": 6, "outcome": "finished", "title": "Deck", "detail": "   "}]),
            POOL,
        )

        assert selection.items[6].detail is None

    def test_a_kept_item_reads_as_its_section_says_and_carries_who_it_is_with(self) -> None:
        pool = {
            1: _candidate("Done thing", CandidateKind.GAIA_DID, state="lookback"),
            2: _candidate("Broke", CandidateKind.NEEDS_YOU, state="failed"),
            3: _candidate("Dan asked", CandidateKind.NEEDS_YOU, state="you"),
        }
        pool[3].people = ["Dan"]
        answer = BriefSelectionAnswer.model_validate(
            {
                "needs_you": [
                    {"id": 1, "action": "review", "title": "Done thing"},
                    {"id": 3, "action": "reply", "title": "Dan asked"},
                ],
                "updates": [{"id": 2, "outcome": "changed", "title": "Broke"}],
            }
        )

        selection = checked_selection(answer, pool)

        assert [(i, item.kind, item.people) for i, item in selection.items.items()] == [
            (1, "you", []),
            (3, "you", ["Dan"]),
            (2, "note", []),
        ]


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    answer = AsyncMock(return_value=_answer())
    monkeypatch.setattr(judge, "ainvoke_structured", answer)
    return answer


class TestTheCandidateLines:
    async def test_a_line_carries_everything_its_producer_knows(self, model: AsyncMock) -> None:
        candidate = BriefCandidate(
            source="gmail",
            app="Gmail",
            kind=CandidateKind.NEEDS_YOU,
            state="you",
            title="Reply to Dan",
            detail="wants the lease",
            due_at=NOW + timedelta(days=1),
            people=["Dan", "Priya"],
            count=2,
            action=BriefAction.REPLY,
            outcome=BriefOutcome.FINISHED,
        )
        model.return_value = BriefSelectionAnswer.model_validate(
            {"needs_you": [{"id": 1, "action": "reply", "title": "Dan"}]}
        )

        await select_candidates(USER_ID, {1: candidate}, {}, NOW, "UTC", kind=BRIEFING_KIND_DAILY)

        assert (
            "1. [Gmail] needs_you: Reply to Dan | wants the lease | due 2026-11-11"
            " | with Dan, Priya | 2 requests, one item | action reply | outcome finished"
        ) in model.await_args.args[1]


class TestTheCall:
    async def test_the_prompt_is_filled_from_the_day_the_clock_the_criteria_and_the_limits(
        self, model: AsyncMock
    ) -> None:
        criteria = {"Linear": "issues assigned to the user", "GitHub": "reviews asked of the user"}

        await select_candidates(
            USER_ID, POOL, criteria, NOW, "Asia/Kolkata", kind=BRIEFING_KIND_DAILY
        )

        prompt = model.await_args.args[1]
        assert "Today is 2026-11-10 (Asia/Kolkata)." in prompt
        assert (
            "- Linear: issues assigned to the user\n- GitHub: reviews asked of the user" in prompt
        )
        assert f"At most {SECTION_CAPS[SectionKey.NEEDS_YOU]}, most important first." in prompt
        assert f"need not act on. At most\n  {SECTION_CAPS[SectionKey.UPDATES]}." in prompt
        assert f"worth a line. At most {SECTION_CAPS[SectionKey.GAIA_DID]}." in prompt
        assert f"one line of {BRIEF_ITEM_DETAIL_MAX_CHARS} characters" in prompt
        assert f"one of {', '.join(BriefAction)}." in prompt
        assert f"one of {', '.join(BriefOutcome)}." in prompt
        assert model.await_args.kwargs["config"] == {"configurable": {"user_id": USER_ID}}

    async def test_with_no_criteria_the_prompt_says_no_app_wrote_any(
        self, model: AsyncMock
    ) -> None:
        await select_candidates(USER_ID, POOL, {}, NOW, "UTC", kind=BRIEFING_KIND_DAILY)

        assert "- (no app wrote criteria)\n" in model.await_args.args[1]

    async def test_one_call_sees_every_candidate_and_each_apps_criteria(
        self, model: AsyncMock
    ) -> None:
        criteria = {"PumpGTM": "replies from leads that wait on the user's decision"}

        selection = await select_candidates(
            USER_ID, POOL, criteria, NOW, "Asia/Kolkata", kind=BRIEFING_KIND_DAILY
        )

        assert selection.sections[SectionKey.LEAD] == [1]
        model.assert_awaited_once()
        prompt = model.await_args.args[1]
        assert "- PumpGTM: replies from leads that wait on the user's decision" in prompt
        assert "1. [PumpGTM] needs_you, important: Neha: can you send pricing" in prompt
        assert "7. [Google Calendar] event: Sequoia" in prompt
        assert "morning brief" in prompt
        assert "3. [GAIA] needs_you: Approve sending the Acme invoice | action approve" in prompt
        assert f"at most {BRIEF_ITEM_TITLE_MAX_CHARS} characters" in prompt
        assert model.await_args.kwargs["label"] == BRIEF_SELECTION_LABEL

    async def test_the_weekly_is_chosen_for_the_week_keeping_finished_work(
        self, model: AsyncMock
    ) -> None:
        await select_candidates(USER_ID, POOL, {}, NOW, "UTC", kind=BRIEFING_KIND_WEEKLY)

        prompt = model.await_args.args[1]
        assert "weekly digest" in prompt and "morning brief" not in prompt
        assert "a finished item is never dropped for being done" in prompt
        assert "6. [GAIA] gaia_did: Investor update" in prompt

    async def test_a_rejected_answer_is_asked_again_once_with_the_problem_named(
        self, model: AsyncMock
    ) -> None:
        model.side_effect = [_answer(needs_you=[3, 4, 99]), _answer()]

        selection = await select_candidates(USER_ID, POOL, {}, NOW, "UTC", kind=BRIEFING_KIND_DAILY)

        assert selection.sections[SectionKey.NEEDS_YOU] == [3, 4]
        first_prompt, retry_prompt = (c.args[1] for c in model.await_args_list)
        assert "rejected" not in first_prompt
        assert retry_prompt == (
            f"{first_prompt}\nYour last answer was rejected: unknown id(s) [99]."
            " Answer again, fixing that."
        )
        assert [c.kwargs["config"] for c in model.await_args_list] == [
            {"configurable": {"user_id": USER_ID}}
        ] * 2

    async def test_a_rejection_is_logged_with_its_problem(self, model: AsyncMock) -> None:
        model.side_effect = [_answer(needs_you=[3, 4, 99]), _answer()]

        async with captured_wide_event() as event:
            await select_candidates(USER_ID, POOL, {}, NOW, "UTC", kind=BRIEFING_KIND_DAILY)

        [warning] = event["warnings"]
        assert (warning["msg"], warning["problem"]) == (
            "briefing.selection_rejected",
            "unknown id(s) [99]",
        )

    async def test_an_over_long_title_is_sent_back_once_never_cut(self, model: AsyncMock) -> None:
        long_title = "Neha from PumpGTM asking for pricing for a 40 person team"
        model.side_effect = [
            _answer(lead={"id": 1, "action": "reply", "title": long_title}),
            _answer(),
        ]

        selection = await select_candidates(USER_ID, POOL, {}, NOW, "UTC", kind=BRIEFING_KIND_DAILY)

        assert selection.items[1].text == "Neha's pricing question"
        retry_prompt = model.await_args_list[1].args[1]
        assert (
            f"Your last answer was rejected: id 1 in lead: a title of {len(long_title)}"
            f" characters, not 1 to {BRIEF_ITEM_TITLE_MAX_CHARS}"
        ) in retry_prompt

    async def test_an_over_long_title_twice_fails_the_brief(self, model: AsyncMock) -> None:
        model.return_value = _answer(updates=[{"id": 5, "outcome": "landed", "title": "z" * 60}])

        with pytest.raises(AppError, match="selection judge broke its contract"):
            await select_candidates(USER_ID, POOL, {}, NOW, "UTC", kind=BRIEFING_KIND_DAILY)

        assert model.await_count == 2

    async def test_an_answer_rejected_twice_fails_the_brief(self, model: AsyncMock) -> None:
        model.return_value = _answer(dropped=[])

        with pytest.raises(AppError, match="selection judge broke its contract"):
            await select_candidates(USER_ID, POOL, {}, NOW, "UTC", kind=BRIEFING_KIND_DAILY)

        assert model.await_count == 2

    async def test_a_day_with_only_the_calendar_makes_no_call(self, model: AsyncMock) -> None:
        selection = await select_candidates(
            USER_ID, {7: POOL[7]}, {}, NOW, "UTC", kind=BRIEFING_KIND_DAILY
        )

        assert selection.sections == {}
        model.assert_not_awaited()
