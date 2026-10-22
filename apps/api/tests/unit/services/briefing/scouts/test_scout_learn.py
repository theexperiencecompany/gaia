"""A scout's learn run through the real agent graph, the real validator and a real replay.

Only the model is scripted: it calls the app's read-only tool, then writes its report.
The freeze is checked by the production playbook validator against the run's own calls,
then replayed with no model through the production runner, exactly as the brief does.
"""

import asyncio
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
import re
from typing import Annotated, Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
import pytest
from tests.factories import make_user_id
import time_machine

from app.agents.middleware.factory import AccountingOptions
from app.agents.prompts.scout_prompts import SCOUT_LEARN_PROMPT
from app.constants.llm import ModelUse
from app.constants.scouts import SCOUT_AGENT_NAME, SCOUT_LEARN_RECURSION_LIMIT
from app.models.agent_config import agent_configurable
from app.models.playbook_models import ToolStep
from app.models.scout_models import ScoutStatus, SignalImportance
from app.services.briefing.scouts import learn
from app.services.briefing.scouts.learn import learn_scout
from app.services.briefing.scouts.tools import ScoutIntegration, ScoutTools
from app.services.briefing.scouts.watch import FrozenWatch, watch
from app.services.workflow.playbook.evaluator import PlaybookUser
from app.services.workflow.playbook.scripted_model import ScriptedCall, ScriptedModel
from app.services.workflow.playbook.tool_graph import run_tool_graph
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

    def __init__(self, issues: list[dict[str, Any]], delay: float = 0) -> None:
        self.issues = issues
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    def tools(self) -> dict[str, BaseTool]:
        @tool
        async def list_issues(assignee: Annotated[str, "Who"], config: RunnableConfig) -> str:
            """List open issues assigned to someone."""
            await asyncio.sleep(self.delay)
            self.calls.append(
                {"assignee": assignee, "user_id": agent_configurable(config)["user_id"]}
            )
            return json.dumps({"data": {"issues": self.issues}})

        return {"list_issues": list_issues}


@tool
async def _delete_issue() -> str:
    """Delete an issue: in the app's registry, never among the scout's read-only tools."""
    return "deleted"


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
    registry = _Registry({**app.tools(), "delete_issue": _delete_issue})
    model = _Learner(script=[ScriptedCall("list_issues", {"assignee": "me"})], report=report)
    with (
        patch.object(learn, "resolve_model", {ModelUse.HELPER: model}.__getitem__),
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
        assert app.calls == [{"assignee": "me", "user_id": USER_ID}] * 3
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

        assert learned.signals == []
        assert learned.scout is not None
        assert learned.scout.status is ScoutStatus.NOTHING_TO_WATCH
        assert learned.scout.playbook is None

    async def test_a_run_that_writes_no_report_fails_loud(self) -> None:
        app = _App([_ISSUE])
        with _seams(app, "I looked around and it seems fine."), pytest.raises(AppError):
            await learn_scout(USER, USER_ID, LINEAR, _tools(app))


@contextmanager
def _spy_graph() -> Iterator[list[dict[str, Any]]]:
    """Record what the learn run asked the graph for, while still running the real one."""
    runs: list[dict[str, Any]] = []

    async def spy(*args: Any, **kwargs: Any) -> list[AnyMessage]:
        runs.append({"args": args, **kwargs})
        return await run_tool_graph(*args, **kwargs)

    with patch.object(learn, "run_tool_graph", spy):
        yield runs


class TestTheLearnRun:
    @time_machine.travel(_NOW, tick=False)
    async def test_the_agent_is_prompted_for_the_app_today_under_the_users_identity(
        self,
    ) -> None:
        app = _App([_ISSUE])
        with _seams(app, _report()), _spy_graph() as runs:
            learned = await learn_scout(USER, USER_ID, LINEAR, _tools(app))

        [run] = runs
        _model, tools, messages = run["args"]
        assert list(tools) == ["list_issues"]
        prompt = SCOUT_LEARN_PROMPT.format(app="Linear", today="2026-10-22", timezone="UTC")
        assert [(type(m), m.content) for m in messages] == [(HumanMessage, prompt)]
        assert run["agent_name"] == SCOUT_AGENT_NAME
        assert run["accounting"] == AccountingOptions(recursion_limit=SCOUT_LEARN_RECURSION_LIMIT)
        configurable = run["configurable"]
        assert set(configurable) == {"stream_id", "user_id", "conversation_id", "execution_mode"}
        assert re.fullmatch(r"scout_[0-9a-f]{32}", configurable["stream_id"])
        assert re.fullmatch(
            rf"scout-linear-{USER_ID}-[0-9a-f]{{6}}", configurable["conversation_id"]
        )
        assert (configurable["user_id"], configurable["execution_mode"]) == (USER_ID, "background")
        assert learned.scout is not None
        assert learned.scout.learned_at == _NOW

    async def test_a_run_past_its_wall_clock_is_cut_off(self) -> None:
        app = _App([_ISSUE], delay=1)
        with (
            _seams(app, _report()),
            patch.object(learn, "SCOUT_LEARN_TIMEOUT", timedelta(milliseconds=50)),
            pytest.raises(TimeoutError),
        ):
            await learn_scout(USER, USER_ID, LINEAR, _tools(app))

    async def test_the_first_block_that_holds_a_report_is_the_report(self) -> None:
        app = _App([_ISSUE])
        text = '```json\n{"not": "a report"}\n```\n' + _report()
        with _seams(app, text):
            learned = await learn_scout(USER, USER_ID, LINEAR, _tools(app))

        assert [s.external_id for s in learned.signals] == ["ENG-12"]

    async def test_a_run_that_writes_no_report_names_the_app_and_quotes_the_reply(self) -> None:
        app = _App([_ISSUE])
        reply = "x" * 300
        with _seams(app, reply), pytest.raises(AppError) as raised:
            await learn_scout(USER, USER_ID, LINEAR, _tools(app))

        error = raised.value
        assert (error.message, error.why, error.fix) == (
            "the linear scout wrote no valid report",
            f"its final message did not hold a ScoutReport (first 200 chars): {'x' * 200!r}",
            "the scout learns again on the next brief",
        )


class TestWhyAReportIsNotFrozen:
    async def _problem(self, report: str) -> str | None:
        app = _App([_ISSUE])
        with _seams(app, report), patch.object(learn, "log") as log:
            learned = await learn_scout(USER, USER_ID, LINEAR, _tools(app))
        assert learned.scout is None
        assert [s.external_id for s in learned.signals] == ["ENG-12"]
        log.warning.assert_called_once_with(
            "briefing.scout_not_frozen",
            integration_id="linear",
            problem=learned.freeze_problem,
        )
        return learned.freeze_problem

    async def test_a_report_with_no_calls(self) -> None:
        assert await self._problem(_report(steps=[], sources=[])) == "the report froze no calls"

    async def test_a_call_that_needs_a_model(self) -> None:
        asks = [{"id": "assigned", "tool": "list_issues", "args": {"assignee": {"$ask": "who?"}}}]
        assert await self._problem(_report(steps=asks)) == (
            "a scout replays with no model, so its calls cannot carry an $ask slot"
        )

    async def test_sources_on_steps_that_were_not_frozen(self) -> None:
        sources = [{**_SOURCE, "step_id": "mine"}, {**_SOURCE, "step_id": "theirs"}]
        assert await self._problem(_report(sources=sources)) == (
            "sources read steps that were not frozen: mine, theirs"
        )

    async def test_every_call_the_run_never_made(self) -> None:
        never_ran = [
            {"id": "assigned", "tool": "list_issues", "args": {"assignee": "bo"}},
            {"id": "also", "tool": "list_issues", "args": {"assignee": "al"}},
        ]
        issue = (
            "list_issues ran 1 time(s) in this run, but never with these args (the last call "
            'used {"assignee": "me"}); freeze the call that ran, with the args that produced '
            "its result, or run it with these args"
        )
        assert await self._problem(_report(steps=never_ran)) == (
            f"steps[0]: {issue}; steps[1]: {issue}"
        )

    async def test_a_call_outside_the_apps_read_only_tools(self) -> None:
        writes = [{"id": "assigned", "tool": "delete_issue", "args": {}}]
        assert await self._problem(_report(steps=writes)) == (
            "steps[0]: no tool named 'delete_issue' exists"
        )
