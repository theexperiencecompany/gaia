"""A scout's learn run through the real agent graph, the real validator and a real replay.

Only the model is scripted: it calls the app's read-only tool, then writes its report.
The freeze is checked by the production playbook validator against the run's own calls,
then replayed with no model through the production runner, exactly as the brief does.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
import json
from typing import Annotated, Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool, tool
import pytest
from tests.factories import make_user_id

from app.models.playbook_models import ToolStep
from app.models.scout_models import ScoutStatus, SignalImportance
from app.services.briefing.scouts import learn
from app.services.briefing.scouts.learn import learn_scout
from app.services.briefing.scouts.tools import ScoutIntegration, ScoutTools
from app.services.briefing.scouts.watch import FrozenWatch, watch
from app.services.workflow.playbook.evaluator import PlaybookUser
from app.services.workflow.playbook.scripted_model import ScriptedCall, ScriptedModel
from app.utils.errors import AppError

USER_ID = make_user_id()
USER = PlaybookUser(email="ada@example.com", name="Ada", timezone="UTC")
LINEAR = ScoutIntegration(integration_id="linear", name="Linear")
_NOW = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)


class _Learner(ScriptedModel):
    """Calls its scripted tools, then answers with the report instead of ending silently."""

    report: str

    def turn_for(self, messages: Sequence[BaseMessage]) -> AIMessage:
        turn = sum(1 for message in messages if isinstance(message, AIMessage))
        if turn >= len(self.script):
            return AIMessage(content=self.report)
        return super().turn_for(messages)


class _App:
    """The app's state: what its list call returns, and every call it received."""

    def __init__(self, issues: list[dict[str, Any]]) -> None:
        self.issues = issues
        self.calls: list[dict[str, Any]] = []

    def tools(self) -> dict[str, BaseTool]:
        @tool
        async def list_issues(assignee: Annotated[str, "Who"]) -> str:
            """List open issues assigned to someone."""
            self.calls.append({"assignee": assignee})
            return json.dumps({"data": {"issues": self.issues}})

        return {"list_issues": list_issues}


class _Registry:
    def __init__(self, tools: dict[str, BaseTool]) -> None:
        self._tools = tools

    def get_tool_dict(self) -> dict[str, BaseTool]:
        return self._tools

    def get_category_of_tool(self, tool_name: str) -> str:
        return "linear"


_ISSUE = {
    "id": "ENG-12",
    "title": "Fix the login redirect",
    "url": "https://linear.app/acme/issue/ENG-12",
    "dueDate": "2026-10-22T18:00:00Z",
    "state": {"name": "In Progress"},
    "creator": {"name": "Priya"},
}

_FIELDS = {
    "external_id": "id",
    "title": "title",
    "url": "url",
    "due_at": "dueDate",
    "state": "state.name",
    "people": "creator.name",
}
_SOURCE = {
    "step_id": "assigned",
    "kind": "issue assigned to you",
    "items_path": "data.issues",
    "fields": _FIELDS,
}


def _report(**overrides: object) -> str:
    report: dict[str, object] = {
        "watching": "Linear issues assigned to the user that are still open",
        "steps": [{"id": "assigned", "tool": "list_issues", "args": {"assignee": "me"}}],
        "sources": [_SOURCE],
        "signals": [
            {
                "external_id": "ENG-12",
                "kind": "issue assigned to you",
                "title": "Fix the login redirect",
                "why": "due this evening",
                "importance": "high",
                "url": "https://linear.app/acme/issue/ENG-12",
            }
        ],
        **overrides,
    }
    return f"```json\n{json.dumps(report)}\n```"


@contextmanager
def _seams(app: _App, report: str) -> Iterator[None]:
    registry = _Registry(app.tools())
    model = _Learner(script=[ScriptedCall("list_issues", {"assignee": "me"})], report=report)
    with (
        patch.object(learn, "resolve_model", return_value=model),
        patch(
            "app.services.workflow.playbook.runner.get_tool_registry",
            AsyncMock(return_value=registry),
        ),
        patch(
            "app.services.workflow.playbook.parser.get_tool_registry",
            AsyncMock(return_value=registry),
        ),
        patch("app.services.hil.gate.resolve_policy", AsyncMock(return_value="allow")),
    ):
        yield


def _tools(app: _App) -> ScoutTools:
    return ScoutTools(read_only=app.tools(), fingerprint="fp-1")


class TestLearnFreezeReplay:
    async def test_a_learn_run_freezes_its_calls_and_the_replay_reads_the_same_items(
        self,
    ) -> None:
        app = _App([_ISSUE])
        with _seams(app, _report()):
            learned = await learn_scout(USER, USER_ID, LINEAR, _tools(app))
            assert learned.scout is not None
            assert learned.scout.playbook is not None
            replayed = await watch(
                USER,
                USER_ID,
                FrozenWatch(LINEAR, learned.scout.playbook, learned.scout.sources),
                app.tools(),
                _NOW,
            )

        scout = learned.scout
        assert (scout.status, scout.tool_fingerprint) == (ScoutStatus.WATCHING, "fp-1")
        assert scout.playbook is not None
        assert scout.playbook.steps == [
            ToolStep(id="assigned", tool="list_issues", args={"assignee": "me"})
        ]
        # The agent's call, the freeze's verification replay, then the brief's replay.
        assert app.calls == [{"assignee": "me"}] * 3
        assert [(s.external_id, s.why, s.importance) for s in learned.signals] == [
            ("ENG-12", "due this evening", SignalImportance.HIGH)
        ]
        [signal] = replayed
        assert (signal.app, signal.external_id, signal.title, signal.state, signal.people) == (
            "Linear",
            "ENG-12",
            "Fix the login redirect",
            "In Progress",
            ["Priya"],
        )
        assert signal.importance is SignalImportance.HIGH

    async def test_a_quiet_day_still_freezes_the_watch(self) -> None:
        app = _App([])
        with _seams(app, _report(signals=[])):
            learned = await learn_scout(USER, USER_ID, LINEAR, _tools(app))

        assert learned.signals == []
        assert learned.scout is not None
        assert learned.scout.status is ScoutStatus.WATCHING

    async def test_a_step_the_run_never_made_is_not_frozen_but_todays_signals_stand(
        self,
    ) -> None:
        app = _App([_ISSUE])
        never_ran = [{"id": "assigned", "tool": "list_issues", "args": {"assignee": "bo"}}]
        with _seams(app, _report(steps=never_ran)):
            learned = await learn_scout(USER, USER_ID, LINEAR, _tools(app))

        assert learned.scout is None
        assert learned.freeze_problem is not None
        assert "never with these args" in learned.freeze_problem
        assert [s.external_id for s in learned.signals] == ["ENG-12"]

    async def test_a_source_whose_paths_miss_the_result_is_not_frozen(self) -> None:
        app = _App([_ISSUE])
        wrong = {**_SOURCE, "fields": {**_FIELDS, "title": "name"}}
        with _seams(app, _report(sources=[wrong])):
            learned = await learn_scout(USER, USER_ID, LINEAR, _tools(app))

        assert learned.scout is None
        assert learned.freeze_problem is not None
        assert "did not replay" in learned.freeze_problem

    async def test_an_app_with_nothing_to_watch_is_recorded_without_calls(self) -> None:
        app = _App([])
        with _seams(app, _report(nothing_to_watch=True, steps=[], sources=[], signals=[])):
            learned = await learn_scout(USER, USER_ID, LINEAR, _tools(app))

        assert learned.scout is not None
        assert learned.scout.status is ScoutStatus.NOTHING_TO_WATCH
        assert learned.scout.playbook is None

    async def test_a_run_that_writes_no_report_fails_loud(self) -> None:
        app = _App([_ISSUE])
        with _seams(app, "I looked around and it seems fine."), pytest.raises(AppError):
            await learn_scout(USER, USER_ID, LINEAR, _tools(app))
