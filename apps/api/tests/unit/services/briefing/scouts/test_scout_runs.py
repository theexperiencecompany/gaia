"""Which scouts replay, relearn, wait out a backoff or are skipped, and that none of it fails the brief.

Faked seams: the plan, the connected integrations, each integration's tools, the learn
run, the replay and the scout store. Assertions are on what each scout contributed and
what was stored.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

from langchain_core.tools import BaseTool, tool
import pytest
from tests.factories import make_user_id
from tests.helpers import captured_wide_event
import time_machine

from app.constants.scouts import SCOUT_RELEARN_BACKOFF
from app.constants.user_activity import ActivityStatus
from app.models.payment_models import PlanType
from app.models.playbook_models import PlaybookBody, ToolStep
from app.models.scout_models import (
    ScoutDocument,
    ScoutOutcome,
    ScoutSkipReason,
    ScoutStatus,
    Signal,
    SignalFields,
    SignalSource,
)
from app.models.user_models import UserDocument
from app.services.briefing.scouts import service
from app.services.briefing.scouts.learn import Learned
from app.services.briefing.scouts.tools import ScoutIntegration, ScoutTools
from app.services.briefing.scouts.watch import FrozenWatch
from app.services.mcp.mcp_client import MCPIntegrationNotFoundError
from app.services.workflow.playbook.evaluator import PlaybookUser
from app.utils.errors import AppError

USER_ID = make_user_id()
_NOW = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)
CRITERIA = "open issues assigned to the user; leave out closed ones"


@tool
def _list_issues() -> str:
    """List the user's open issues."""
    return "[]"


USER = UserDocument(id=USER_ID, email="ada@example.com", name="Ada", timezone="Asia/Kolkata")
ADA = PlaybookUser(email="ada@example.com", name="Ada", timezone="Asia/Kolkata")
LINEAR = ScoutIntegration(integration_id="linear", name="Linear")
GITHUB = ScoutIntegration(integration_id="github", name="GitHub")
READ_ONLY: dict[str, BaseTool] = {"list_issues": _list_issues}
_SOURCE = SignalSource(
    step_id="assigned", kind="issue", fields=SignalFields(external_id="id", title="title")
)


def _tools(integration_id: str = "linear", fingerprint: str = "fp-1") -> ScoutTools:
    return ScoutTools(
        integration_id=integration_id, read_only=READ_ONLY, total=3, fingerprint=fingerprint
    )


def _signal(integration: ScoutIntegration, external_id: str) -> Signal:
    return Signal(
        integration_id=integration.integration_id,
        app=integration.name,
        external_id=external_id,
        kind="issue",
        title=f"Item {external_id}",
    )


def _scout(
    integration: ScoutIntegration,
    *,
    fingerprint: str = "fp-1",
    status: ScoutStatus = ScoutStatus.WATCHING,
) -> ScoutDocument:
    watching = status is ScoutStatus.WATCHING
    return ScoutDocument(
        user_id=USER_ID,
        integration_id=integration.integration_id,
        status=status,
        tool_fingerprint=fingerprint,
        playbook=PlaybookBody(
            description="open issues",
            steps=[ToolStep(id="assigned", tool="list_issues")],
            result_brief="-",
        )
        if watching
        else None,
        sources=[_SOURCE] if watching else [],
        criteria=CRITERIA if watching else "",
        learned_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


def _failed(streak: int, next_learn_at: datetime, fingerprint: str = "fp-1") -> ScoutDocument:
    return ScoutDocument(
        user_id=USER_ID,
        integration_id="linear",
        status=ScoutStatus.LEARN_FAILED,
        tool_fingerprint=fingerprint,
        learned_at=_NOW - timedelta(days=1),
        failed_learns=streak,
        next_learn_at=next_learn_at,
    )


@dataclass
class Scouts:
    """Every seam a scout run touches, with a happy-path default."""

    integrations: list[ScoutIntegration] = field(default_factory=lambda: [LINEAR])
    stored: dict[str, ScoutDocument] = field(default_factory=dict)
    fingerprint: str = "fp-1"
    read_only: dict[str, BaseTool] = field(default_factory=lambda: dict(READ_ONLY))
    plan: PlanType = PlanType.PRO
    activity: ActivityStatus = ActivityStatus.ACTIVE
    may_learn: bool = True
    learn: AsyncMock = field(default_factory=AsyncMock)
    watch: AsyncMock = field(default_factory=AsyncMock)
    broken_tools: dict[str, Exception] = field(default_factory=dict)

    async def replace(self, scout: ScoutDocument) -> None:
        self.stored[scout.integration_id] = scout


@pytest.fixture
def scouts(monkeypatch: pytest.MonkeyPatch) -> Iterator[Scouts]:
    s = Scouts()
    s.learn.side_effect = lambda user, user_id, integration, tools: Learned(
        signals=[_signal(integration, "learned-1")],
        scout=_scout(integration, fingerprint=tools.fingerprint),
    )
    s.watch.side_effect = lambda user, user_id, frozen, tools: [
        _signal(frozen.integration, "replayed-1")
    ]

    async def tools(user_id: str, integration_id: str) -> ScoutTools:
        assert user_id == USER_ID
        if integration_id in s.broken_tools:
            raise s.broken_tools[integration_id]
        return ScoutTools(
            integration_id=integration_id,
            read_only=s.read_only,
            total=3,
            fingerprint=s.fingerprint,
        )

    async def find_for(user_id: str, integration_id: str) -> ScoutDocument | None:
        assert user_id == USER_ID
        return s.stored.get(integration_id)

    async def may_learn(user_id: str) -> bool:
        assert user_id == USER_ID
        return s.may_learn

    async def integrations(user_id: str) -> list[ScoutIntegration]:
        assert user_id == USER_ID
        return s.integrations

    async def activity(user_id: str) -> ActivityStatus:
        assert user_id == USER_ID
        return s.activity

    async def plan(user_id: str) -> PlanType:
        assert user_id == USER_ID
        return s.plan

    monkeypatch.setattr(service, "scout_integrations", integrations)
    monkeypatch.setattr(service, "scout_tools", tools)
    monkeypatch.setattr(service.scouts_repository, "find_for", find_for)
    monkeypatch.setattr(service.scouts_repository, "replace", s.replace)
    monkeypatch.setattr(service, "learn_scout", s.learn)
    monkeypatch.setattr(service, "watch", s.watch)
    monkeypatch.setattr(service, "may_learn", may_learn)
    monkeypatch.setattr(service, "activity_status_of", activity)
    monkeypatch.setattr(service.payment_service, "get_cached_plan_type", plan)
    with time_machine.travel(_NOW, tick=False):
        yield s


def _ids(result: Any) -> list[str]:
    return [signal.external_id for signal in result.signals]


class TestReplayOrLearn:
    async def test_a_new_integration_is_learned_and_its_watch_frozen(self, scouts: Scouts) -> None:
        [result] = await service.run_scouts(USER)

        assert (result.outcome, _ids(result)) == (ScoutOutcome.LEARNED, ["learned-1"])
        assert scouts.stored["linear"] == _scout(LINEAR)
        scouts.watch.assert_not_awaited()

    async def test_a_frozen_watch_replays_with_no_learn_and_carries_its_criteria(
        self, scouts: Scouts
    ) -> None:
        scouts.stored["linear"] = _scout(LINEAR)

        [result] = await service.run_scouts(USER)

        assert (result.outcome, _ids(result)) == (ScoutOutcome.REPLAYED, ["replayed-1"])
        assert result.criteria == CRITERIA
        scouts.learn.assert_not_awaited()

    async def test_a_changed_tool_list_relearns_and_refreezes(self, scouts: Scouts) -> None:
        scouts.stored["linear"] = _scout(LINEAR, fingerprint="fp-old")
        scouts.fingerprint = "fp-new"

        [result] = await service.run_scouts(USER)

        assert result.outcome is ScoutOutcome.LEARNED
        scouts.watch.assert_not_awaited()
        assert scouts.stored["linear"] == _scout(LINEAR, fingerprint="fp-new")

    async def test_a_failed_replay_relearns_exactly_once(self, scouts: Scouts) -> None:
        scouts.stored["linear"] = _scout(LINEAR)
        scouts.watch.side_effect = AppError(message="scout replay stopped")

        [result] = await service.run_scouts(USER)

        assert (result.outcome, _ids(result)) == (ScoutOutcome.LEARNED, ["learned-1"])
        assert scouts.learn.await_count == 1

    async def test_a_watch_frozen_without_criteria_relearns_instead_of_replaying(
        self, scouts: Scouts
    ) -> None:
        scouts.stored["linear"] = _scout(LINEAR).model_copy(update={"criteria": ""})

        [result] = await service.run_scouts(USER)

        assert result.outcome is ScoutOutcome.LEARNED
        scouts.watch.assert_not_awaited()
        assert scouts.stored["linear"].criteria == CRITERIA

    async def test_nothing_to_watch_is_skipped_until_the_tools_change(self, scouts: Scouts) -> None:
        scouts.stored["linear"] = _scout(LINEAR, status=ScoutStatus.NOTHING_TO_WATCH)

        [result] = await service.run_scouts(USER)
        assert (result.outcome, result.signals) == (ScoutOutcome.NOTHING_TO_WATCH, [])
        scouts.learn.assert_not_awaited()

        scouts.fingerprint = "fp-2"
        [result] = await service.run_scouts(USER)
        assert result.outcome is ScoutOutcome.LEARNED

    async def test_a_learn_over_the_daily_ceiling_is_skipped_as_budget(
        self, scouts: Scouts
    ) -> None:
        scouts.may_learn = False

        [result] = await service.run_scouts(USER)

        assert (result.outcome, result.skip_reason) == (
            ScoutOutcome.SKIPPED,
            ScoutSkipReason.BUDGET,
        )
        scouts.learn.assert_not_awaited()


class TestWhoRunsScouts:
    async def test_a_free_user_runs_no_scout_and_spends_nothing(self, scouts: Scouts) -> None:
        scouts.plan = PlanType.FREE

        async with captured_wide_event() as event:
            assert await service.run_scouts(USER) == []

        scouts.learn.assert_not_awaited()
        scouts.watch.assert_not_awaited()
        assert event["scouts"] == {"skipped": "free_plan"}

    async def test_a_free_users_new_connection_is_not_scouted(self, scouts: Scouts) -> None:
        scouts.plan = PlanType.FREE

        assert await service.learn_connected_integration(USER, "linear") is None
        scouts.learn.assert_not_awaited()

    async def test_a_dormant_user_runs_no_scout(self, scouts: Scouts) -> None:
        scouts.activity = ActivityStatus.DORMANT

        async with captured_wide_event() as event:
            assert await service.run_scouts(USER) == []

        scouts.learn.assert_not_awaited()
        assert event["scouts"] == {"skipped": "dormant"}


class TestTypedSkips:
    async def test_a_stale_integration_record_is_skipped_without_an_error(
        self, scouts: Scouts
    ) -> None:
        scouts.integrations = [ScoutIntegration("google_calendar", "google_calendar"), LINEAR]
        scouts.broken_tools = {"google_calendar": MCPIntegrationNotFoundError("google_calendar")}
        scouts.stored["linear"] = _scout(LINEAR)

        async with captured_wide_event() as event:
            stale, linear = await service.run_scouts(USER)

        assert (stale.outcome, stale.skip_reason, stale.error) == (
            ScoutOutcome.SKIPPED,
            ScoutSkipReason.UNKNOWN_INTEGRATION,
            None,
        )
        assert linear.outcome is ScoutOutcome.REPLAYED
        assert "errors" not in event
        scouts.learn.assert_not_awaited()

    async def test_an_integration_with_no_read_only_tool_is_never_learned(
        self, scouts: Scouts
    ) -> None:
        scouts.read_only = {}

        [result] = await service.run_scouts(USER)

        assert result.skip_reason is ScoutSkipReason.NO_READ_ONLY_TOOLS
        scouts.learn.assert_not_awaited()
        assert scouts.stored == {}


class TestBackoff:
    async def test_a_learn_that_will_not_freeze_waits_a_day_before_the_next(
        self, scouts: Scouts
    ) -> None:
        scouts.learn.side_effect = lambda *_: Learned(
            signals=[_signal(LINEAR, "learned-1")], scout=None, freeze_problem="no calls"
        )

        [result] = await service.run_scouts(USER)

        assert _ids(result) == ["learned-1"]
        assert scouts.stored["linear"] == _failed(1, _NOW + SCOUT_RELEARN_BACKOFF[0]).model_copy(
            update={"learned_at": _NOW}
        )

    async def test_a_learn_that_raises_also_starts_the_backoff(self, scouts: Scouts) -> None:
        scouts.learn.side_effect = TimeoutError()

        [result] = await service.run_scouts(USER)

        assert result.skip_reason is ScoutSkipReason.FAILED
        stored = scouts.stored["linear"]
        assert (stored.status, stored.failed_learns, stored.next_learn_at) == (
            ScoutStatus.LEARN_FAILED,
            1,
            _NOW + SCOUT_RELEARN_BACKOFF[0],
        )

    async def test_inside_the_backoff_the_scout_is_skipped_without_a_learn(
        self, scouts: Scouts
    ) -> None:
        scouts.stored["linear"] = _failed(1, _NOW + timedelta(seconds=1))

        [result] = await service.run_scouts(USER)

        assert (result.outcome, result.skip_reason) == (
            ScoutOutcome.SKIPPED,
            ScoutSkipReason.BACKOFF,
        )
        scouts.learn.assert_not_awaited()

    async def test_each_failure_in_a_row_waits_longer_up_to_the_last_step(
        self, scouts: Scouts
    ) -> None:
        scouts.learn.side_effect = lambda *_: Learned(signals=[], scout=None, freeze_problem="x")
        waits = []
        for streak in range(1, len(SCOUT_RELEARN_BACKOFF) + 2):
            scouts.stored["linear"] = _failed(streak - 1, _NOW)
            await service.run_scouts(USER)
            stored = scouts.stored["linear"]
            assert stored.failed_learns == streak
            assert stored.next_learn_at is not None
            waits.append(stored.next_learn_at - _NOW)

        assert waits == [*SCOUT_RELEARN_BACKOFF, SCOUT_RELEARN_BACKOFF[-1]]

    async def test_new_tools_end_the_backoff_and_restart_the_streak(self, scouts: Scouts) -> None:
        scouts.stored["linear"] = _failed(2, _NOW + timedelta(days=3), fingerprint="fp-old")
        scouts.learn.side_effect = lambda *_: Learned(signals=[], scout=None, freeze_problem="x")

        await service.run_scouts(USER)

        scouts.learn.assert_awaited_once()
        assert scouts.stored["linear"].failed_learns == 1

    async def test_a_successful_learn_after_the_backoff_watches_again(self, scouts: Scouts) -> None:
        scouts.stored["linear"] = _failed(3, _NOW)

        [result] = await service.run_scouts(USER)

        assert result.outcome is ScoutOutcome.LEARNED
        assert scouts.stored["linear"] == _scout(LINEAR)


class TestOneScoutFailing:
    async def test_a_failing_scout_is_a_typed_skip_and_the_others_still_report(
        self, scouts: Scouts
    ) -> None:
        scouts.integrations = [GITHUB, LINEAR]
        scouts.broken_tools = {"github": AppError(message="no tools reachable for github")}
        scouts.stored["linear"] = _scout(LINEAR)

        async with captured_wide_event() as event:
            github, linear = await service.run_scouts(USER)

        assert (github.outcome, github.skip_reason) == (
            ScoutOutcome.SKIPPED,
            ScoutSkipReason.FAILED,
        )
        assert github.error == "AppError: no tools reachable for github"
        assert (linear.outcome, _ids(linear)) == (ScoutOutcome.REPLAYED, ["replayed-1"])
        [error] = event["errors"]
        assert error["integration_id"] == "github"


class TestWhatEachScoutIsHanded:
    async def test_a_learn_is_handed_the_user_their_tools_and_the_integration(
        self, scouts: Scouts
    ) -> None:
        await service.run_scouts(USER)

        scouts.learn.assert_awaited_once_with(ADA, USER_ID, LINEAR, _tools())

    async def test_a_user_with_no_profile_learns_as_nobody_in_utc(self, scouts: Scouts) -> None:
        bare = UserDocument(id=USER_ID, email=None, name=None, timezone=None)

        await service.run_scouts(bare)

        [user, *_] = scouts.learn.await_args.args
        assert user == PlaybookUser(email="", name="", timezone="UTC")

    async def test_a_replay_is_handed_the_frozen_watch_and_the_read_only_tools(
        self, scouts: Scouts
    ) -> None:
        scout = _scout(LINEAR)
        scouts.stored["linear"] = scout

        await service.run_scouts(USER)

        assert scout.playbook is not None
        scouts.watch.assert_awaited_once_with(
            ADA, USER_ID, FrozenWatch(LINEAR, scout.playbook, [_SOURCE]), READ_ONLY
        )


class TestTheWideEvent:
    async def test_the_run_records_each_outcome_skip_and_the_signal_count(
        self, scouts: Scouts
    ) -> None:
        scouts.integrations = [GITHUB, LINEAR]
        scouts.stored["linear"] = _scout(LINEAR)
        scouts.may_learn = False

        async with captured_wide_event() as event:
            await service.run_scouts(USER)

        assert event["scouts"] == {
            "outcomes": {"github": "skipped", "linear": "replayed"},
            "skip_reasons": {"github": "budget"},
            "signal_count": 1,
        }

    async def test_a_relearn_records_why_the_replay_failed(self, scouts: Scouts) -> None:
        scouts.stored["linear"] = _scout(LINEAR)
        scouts.watch.side_effect = AppError(message="scout replay stopped")

        async with captured_wide_event() as event:
            await service.run_scouts(USER)

        assert event["warnings"] == [
            {
                "msg": "briefing.scout_relearn",
                "integration_id": "linear",
                "reason": "scout replay stopped",
                "error_type": "AppError",
            }
        ]
