"""Which scouts replay, which relearn, and that one failing scout never costs the brief the rest.

Faked seams: the connected integrations, each integration's tools, the learn run, the
replay and the scout store. Assertions are on what each scout contributed and what was stored.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

from langchain_core.tools import BaseTool, tool
import pytest
from tests.factories import make_user_id
from tests.helpers import captured_wide_event
import time_machine

from app.constants.user_activity import ActivityStatus
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
from app.services.workflow.playbook.evaluator import PlaybookUser
from app.utils.errors import AppError

USER_ID = make_user_id()
_NOW = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)


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
        if status is ScoutStatus.WATCHING
        else None,
        sources=[_SOURCE] if status is ScoutStatus.WATCHING else [],
        learned_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


@dataclass
class Scouts:
    """Every seam a scout run touches, with a happy-path default."""

    integrations: list[ScoutIntegration] = field(default_factory=lambda: [LINEAR])
    stored: dict[str, ScoutDocument] = field(default_factory=dict)
    fingerprint: str = "fp-1"
    activity: ActivityStatus = ActivityStatus.ACTIVE
    may_learn: bool = True
    learn: AsyncMock = field(default_factory=AsyncMock)
    watch: AsyncMock = field(default_factory=AsyncMock)
    replace: AsyncMock = field(default_factory=AsyncMock)
    delete: AsyncMock = field(default_factory=AsyncMock)
    broken_tools: set[str] = field(default_factory=set)


@pytest.fixture
def scouts(monkeypatch: pytest.MonkeyPatch) -> Iterator[Scouts]:
    s = Scouts()
    s.learn.side_effect = lambda user, user_id, integration, tools: Learned(
        signals=[_signal(integration, "learned-1")],
        scout=_scout(integration, fingerprint=tools.fingerprint),
    )
    s.watch.side_effect = lambda user, user_id, frozen, tools, now: [
        _signal(frozen.integration, "replayed-1")
    ]

    async def tools(user_id: str, integration_id: str) -> ScoutTools:
        assert user_id == USER_ID
        if integration_id in s.broken_tools:
            raise AppError(message=f"no tools reachable for {integration_id}")
        return ScoutTools(read_only=READ_ONLY, fingerprint=s.fingerprint)

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

    monkeypatch.setattr(service, "scout_integrations", integrations)
    monkeypatch.setattr(service, "scout_tools", tools)
    monkeypatch.setattr(service.scouts_repository, "find_for", find_for)
    monkeypatch.setattr(service.scouts_repository, "replace", s.replace)
    monkeypatch.setattr(service.scouts_repository, "delete_for", s.delete)
    monkeypatch.setattr(service, "learn_scout", s.learn)
    monkeypatch.setattr(service, "watch", s.watch)
    monkeypatch.setattr(service, "may_learn", may_learn)
    monkeypatch.setattr(service, "tallied_learn", _untallied)
    monkeypatch.setattr(service, "activity_status_of", activity)
    return s


@asynccontextmanager
async def _untallied(user_id: str) -> AsyncIterator[None]:
    assert user_id == USER_ID
    yield


def _ids(result: Any) -> list[str]:
    return [signal.external_id for signal in result.signals]


class TestReplayOrLearn:
    async def test_a_new_integration_is_learned_and_its_watch_frozen(self, scouts: Scouts) -> None:
        [result] = await service.run_scouts(USER)

        assert (result.outcome, _ids(result)) == (ScoutOutcome.LEARNED, ["learned-1"])
        scouts.replace.assert_awaited_once_with(_scout(LINEAR))
        scouts.watch.assert_not_awaited()

    async def test_a_frozen_watch_replays_with_no_learn(self, scouts: Scouts) -> None:
        scouts.stored["linear"] = _scout(LINEAR)

        [result] = await service.run_scouts(USER)

        assert (result.outcome, _ids(result)) == (ScoutOutcome.REPLAYED, ["replayed-1"])
        scouts.learn.assert_not_awaited()
        assert scouts.watch.await_args.args[2].playbook == _scout(LINEAR).playbook

    async def test_a_changed_tool_list_relearns_and_refreezes(self, scouts: Scouts) -> None:
        scouts.stored["linear"] = _scout(LINEAR, fingerprint="fp-old")
        scouts.fingerprint = "fp-new"

        [result] = await service.run_scouts(USER)

        assert result.outcome is ScoutOutcome.LEARNED
        scouts.watch.assert_not_awaited()
        scouts.replace.assert_awaited_once_with(_scout(LINEAR, fingerprint="fp-new"))

    async def test_a_failed_replay_relearns_exactly_once(self, scouts: Scouts) -> None:
        scouts.stored["linear"] = _scout(LINEAR)
        scouts.watch.side_effect = AppError(message="scout replay stopped")

        [result] = await service.run_scouts(USER)

        assert (result.outcome, _ids(result)) == (ScoutOutcome.LEARNED, ["learned-1"])
        assert scouts.learn.await_count == 1
        scouts.replace.assert_awaited_once()

    async def test_a_relearn_that_will_not_freeze_drops_the_stale_watch(
        self, scouts: Scouts
    ) -> None:
        scouts.stored["linear"] = _scout(LINEAR)
        scouts.watch.side_effect = AppError(message="scout replay stopped")
        scouts.learn.side_effect = lambda *_: Learned(
            signals=[_signal(LINEAR, "learned-1")], scout=None, freeze_problem="no calls"
        )

        [result] = await service.run_scouts(USER)

        assert _ids(result) == ["learned-1"]
        scouts.replace.assert_not_awaited()
        scouts.delete.assert_awaited_once_with(USER_ID, "linear")

    async def test_nothing_to_watch_is_skipped_until_the_tools_change(self, scouts: Scouts) -> None:
        scouts.stored["linear"] = _scout(LINEAR, status=ScoutStatus.NOTHING_TO_WATCH)

        [result] = await service.run_scouts(USER)
        assert (result.outcome, result.signals) == (ScoutOutcome.NOTHING_TO_WATCH, [])
        scouts.learn.assert_not_awaited()
        scouts.watch.assert_not_awaited()

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

    async def test_a_dormant_user_runs_no_scout(self, scouts: Scouts) -> None:
        scouts.activity = ActivityStatus.DORMANT

        assert await service.run_scouts(USER) == []
        scouts.learn.assert_not_awaited()
        scouts.watch.assert_not_awaited()


class TestOneScoutFailing:
    async def test_a_failing_scout_is_a_typed_skip_and_the_others_still_report(
        self, scouts: Scouts
    ) -> None:
        scouts.integrations = [GITHUB, LINEAR]
        scouts.broken_tools = {"github"}
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

    async def test_a_learn_that_raises_skips_only_that_scout(self, scouts: Scouts) -> None:
        scouts.integrations = [GITHUB, LINEAR]
        scouts.stored["linear"] = _scout(LINEAR)
        scouts.learn.side_effect = TimeoutError()

        github, linear = await service.run_scouts(USER)

        assert github.skip_reason is ScoutSkipReason.FAILED
        assert linear.outcome is ScoutOutcome.REPLAYED


class TestANewConnection:
    async def test_a_connected_integration_is_learned_ahead_of_the_brief(
        self, scouts: Scouts
    ) -> None:
        result = await service.learn_connected_integration(USER, "linear")

        assert result is not None
        assert result.outcome is ScoutOutcome.LEARNED
        scouts.replace.assert_awaited_once()

    async def test_an_integration_no_scout_watches_is_left_alone(self, scouts: Scouts) -> None:
        assert await service.learn_connected_integration(USER, "gmail") is None
        scouts.learn.assert_not_awaited()


class TestWhatEachScoutIsHanded:
    async def test_a_learn_is_handed_the_user_their_tools_and_the_integration(
        self, scouts: Scouts
    ) -> None:
        await service.run_scouts(USER)

        scouts.learn.assert_awaited_once_with(
            ADA, USER_ID, LINEAR, ScoutTools(read_only=READ_ONLY, fingerprint="fp-1")
        )

    async def test_a_user_with_no_profile_learns_as_nobody_in_utc(self, scouts: Scouts) -> None:
        bare = UserDocument(id=USER_ID, email=None, name=None, timezone=None)

        await service.run_scouts(bare)

        [user, *_] = scouts.learn.await_args.args
        assert user == PlaybookUser(email="", name="", timezone="UTC")

    @time_machine.travel(_NOW, tick=False)
    async def test_a_replay_is_handed_the_frozen_watch_and_the_read_only_tools_now(
        self, scouts: Scouts
    ) -> None:
        scout = _scout(LINEAR)
        scouts.stored["linear"] = scout

        await service.run_scouts(USER)

        assert scout.playbook is not None
        scouts.watch.assert_awaited_once_with(
            ADA, USER_ID, FrozenWatch(LINEAR, scout.playbook, [_SOURCE]), READ_ONLY, _NOW
        )


class TestWhatALearnLeavesBehind:
    async def test_a_learn_that_finds_nothing_to_watch_says_so(self, scouts: Scouts) -> None:
        scouts.learn.side_effect = lambda *_: Learned(
            signals=[], scout=_scout(LINEAR, status=ScoutStatus.NOTHING_TO_WATCH)
        )

        [result] = await service.run_scouts(USER)

        assert result.outcome is ScoutOutcome.NOTHING_TO_WATCH

    async def test_a_watch_whose_tools_changed_and_will_not_refreeze_is_dropped(
        self, scouts: Scouts
    ) -> None:
        scouts.stored["linear"] = _scout(LINEAR, fingerprint="fp-old")
        scouts.learn.side_effect = lambda *_: Learned(signals=[], scout=None, freeze_problem="x")

        await service.run_scouts(USER)

        scouts.delete.assert_awaited_once_with(USER_ID, "linear")

    async def test_a_watch_that_lost_its_calls_is_relearned_and_dropped_if_it_will_not_freeze(
        self, scouts: Scouts
    ) -> None:
        scouts.stored["linear"] = _scout(LINEAR).model_copy(update={"playbook": None})
        scouts.learn.side_effect = lambda *_: Learned(
            signals=[_signal(LINEAR, "learned-1")], scout=None, freeze_problem="x"
        )

        [result] = await service.run_scouts(USER)

        assert (result.outcome, _ids(result)) == (ScoutOutcome.LEARNED, ["learned-1"])
        scouts.learn.assert_awaited_once_with(
            ADA, USER_ID, LINEAR, ScoutTools(read_only=READ_ONLY, fingerprint="fp-1")
        )
        scouts.delete.assert_awaited_once_with(USER_ID, "linear")


class TestTheWideEvent:
    async def test_the_run_records_each_outcome_and_the_signal_count(self, scouts: Scouts) -> None:
        scouts.integrations = [GITHUB, LINEAR]
        scouts.stored["linear"] = _scout(LINEAR)

        async with captured_wide_event() as event:
            await service.run_scouts(USER)

        assert event["scouts"] == {
            "outcomes": {"github": "learned", "linear": "replayed"},
            "signal_count": 2,
        }

    async def test_a_dormant_user_is_recorded_as_skipped(self, scouts: Scouts) -> None:
        scouts.activity = ActivityStatus.DORMANT

        async with captured_wide_event() as event:
            await service.run_scouts(USER)

        assert event["scouts"] == {"skipped": "dormant"}

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

    async def test_a_failed_scout_records_its_error(self, scouts: Scouts) -> None:
        scouts.broken_tools = {"linear"}

        async with captured_wide_event() as event:
            await service.run_scouts(USER)

        assert event["errors"] == [
            {
                "msg": "briefing.scout_failed",
                "integration_id": "linear",
                "error": "no tools reachable for linear",
                "error_type": "AppError",
            }
        ]
