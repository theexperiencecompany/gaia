"""Judging replayed signals in one call across every app, and what a failed judge costs the brief.

The judge's model call is the only faked seam in the judge tests; the brief-side tests
also fake the scout run and memory around it.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from tests.factories import make_user_id
from tests.helpers import captured_wide_event

from app.constants.scouts import SIGNAL_JUDGE_LABEL
from app.models.scout_models import (
    RememberedSignal,
    ScoutOutcome,
    ScoutResult,
    Signal,
    SignalImportance,
    SignalMemoryDocument,
)
from app.models.user_models import UserDocument
from app.services.briefing.scouts import judge, service
from app.services.briefing.scouts.judge import SignalVerdict, SignalVerdicts, judge_replayed
from app.utils.errors import AppError

USER_ID = make_user_id()
NOW = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)
TODOIST_CRITERIA = "work tasks due soon or overdue; routines like the gym are not news"
PUMP_CRITERIA = "replies from leads that wait on the user's decision"


def _signal(integration_id: str, app: str, external_id: str, title: str) -> Signal:
    return Signal(
        integration_id=integration_id,
        app=app,
        external_id=external_id,
        kind="item",
        title=title,
    )


GYM = _signal("todoist", "Todoist", "t1", "Gym")
GST = _signal("todoist", "Todoist", "t2", "File GST return")
NEHA = _signal("pump", "PumpGTM", "r1", "Neha: can you send pricing for a 40 person team?")
LEARNED = _signal("github", "GitHub", "g1", "Review the barge-in PR")


def _remembered(signal: Signal, memory: SignalMemoryDocument | None = None) -> RememberedSignal:
    return RememberedSignal(signal=signal, memory=memory)


RESULTS = [
    ScoutResult(
        integration_id="todoist",
        outcome=ScoutOutcome.REPLAYED,
        signals=[GYM, GST],
        criteria=TODOIST_CRITERIA,
    ),
    ScoutResult(
        integration_id="pump", outcome=ScoutOutcome.REPLAYED, signals=[NEHA], criteria=PUMP_CRITERIA
    ),
    ScoutResult(integration_id="github", outcome=ScoutOutcome.LEARNED, signals=[LEARNED]),
]
REMEMBERED = [_remembered(GYM), _remembered(GST), _remembered(NEHA), _remembered(LEARNED)]


def _verdicts(*calls: tuple[bool, SignalImportance]) -> SignalVerdicts:
    return SignalVerdicts(
        verdicts=[
            SignalVerdict(number=n, keep=keep, importance=importance, why=f"why {n}")
            for n, (keep, importance) in enumerate(calls, start=1)
        ]
    )


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    answer = AsyncMock(
        return_value=_verdicts(
            (False, SignalImportance.NORMAL),
            (True, SignalImportance.HIGH),
            (True, SignalImportance.HIGH),
        )
    )
    monkeypatch.setattr(judge, "ainvoke_structured", answer)
    return answer


class TestJudge:
    async def test_noise_is_dropped_and_a_person_waiting_stays_high(self, model: AsyncMock) -> None:
        """Replay emitted every row: gym and protein reached the brief beside Neha's pricing ask."""
        kept = await judge_replayed(USER_ID, RESULTS, REMEMBERED, NOW, "Asia/Kolkata")

        assert [(r.signal.external_id, r.signal.importance, r.signal.why) for r in kept] == [
            ("t2", SignalImportance.HIGH, "why 2"),
            ("r1", SignalImportance.HIGH, "why 3"),
            ("g1", SignalImportance.NORMAL, None),
        ]

    async def test_every_app_is_judged_in_one_call_with_its_criteria_and_memory(
        self, model: AsyncMock
    ) -> None:
        shown_twice = SignalMemoryDocument(
            user_id=USER_ID,
            integration_id="todoist",
            external_id="t1",
            first_seen=NOW - timedelta(days=3),
            times_shown=2,
            last_shown=NOW - timedelta(days=1),
        )
        remembered = [_remembered(GYM, shown_twice), *REMEMBERED[1:]]

        await judge_replayed(USER_ID, RESULTS, remembered, NOW, "Asia/Kolkata")

        model.assert_awaited_once()
        schema, prompt = model.await_args.args
        assert schema is SignalVerdicts
        assert model.await_args.kwargs["label"] == SIGNAL_JUDGE_LABEL
        assert model.await_args.kwargs["config"] == {"configurable": {"user_id": USER_ID}}
        assert f"- Todoist: {TODOIST_CRITERIA}\n- PumpGTM: {PUMP_CRITERIA}" in prompt
        assert (
            "1. [Todoist] item: Gym | first seen 3 days ago, mentioned 2 time(s), last yesterday"
        ) in prompt
        assert "3. [PumpGTM] item: Neha" in prompt
        assert "Review the barge-in PR" not in prompt
        assert "2026-10-22 (Asia/Kolkata)" in prompt

    async def test_with_nothing_replayed_there_is_no_call(self, model: AsyncMock) -> None:
        kept = await judge_replayed(USER_ID, RESULTS[2:], REMEMBERED[3:], NOW, "UTC")

        assert kept == REMEMBERED[3:]
        model.assert_not_awaited()

    @pytest.mark.parametrize(
        "verdicts",
        [
            _verdicts((True, SignalImportance.HIGH), (True, SignalImportance.HIGH)),
            SignalVerdicts(
                verdicts=[
                    SignalVerdict(number=n, keep=True, importance="normal", why="x")
                    for n in (1, 1, 2)
                ]
            ),
            SignalVerdicts(
                verdicts=[
                    SignalVerdict(number=n, keep=True, importance="normal", why="x")
                    for n in (1, 2, 4)
                ]
            ),
        ],
        ids=["one short", "a number twice", "a number out of range"],
    )
    async def test_an_answer_that_misses_an_item_fails_loud(
        self, monkeypatch: pytest.MonkeyPatch, verdicts: SignalVerdicts
    ) -> None:
        monkeypatch.setattr(judge, "ainvoke_structured", AsyncMock(return_value=verdicts))

        with pytest.raises(AppError) as raised:
            await judge_replayed(USER_ID, RESULTS, REMEMBERED, NOW, "UTC")

        assert raised.value.message == "the signal judge did not answer every item once"


USER = UserDocument(id=USER_ID, email="ada@example.com", name="Ada", timezone="Asia/Kolkata")


@pytest.fixture
def brief_seams(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    async def run_scouts(user: UserDocument) -> list[ScoutResult]:
        assert user is USER
        return RESULTS

    async def remember(user_id: str, signals: list[Signal], now: datetime) -> list:
        assert (user_id, signals, now) == (USER_ID, [GYM, GST, NEHA, LEARNED], NOW)
        return REMEMBERED

    monkeypatch.setattr(service, "run_scouts", run_scouts)
    monkeypatch.setattr(service, "remember", remember)
    judged = AsyncMock(return_value=REMEMBERED[1:])
    monkeypatch.setattr(service, "judge_replayed", judged)
    return judged


class TestScoutSignals:
    async def test_the_brief_gets_the_judged_signals(self, brief_seams: AsyncMock) -> None:
        assert await service.scout_signals(USER, NOW) == REMEMBERED[1:]
        brief_seams.assert_awaited_once_with(USER_ID, RESULTS, REMEMBERED, NOW, "Asia/Kolkata")

    async def test_a_failed_judge_costs_only_the_replayed_signals(
        self, brief_seams: AsyncMock
    ) -> None:
        brief_seams.side_effect = TimeoutError("judge timed out")

        async with captured_wide_event() as event:
            kept = await service.scout_signals(USER, NOW)

        assert kept == REMEMBERED[3:]
        assert event["errors"] == [
            {
                "msg": "briefing.signal_judge_failed",
                "error": "judge timed out",
                "error_type": "TimeoutError",
            }
        ]
