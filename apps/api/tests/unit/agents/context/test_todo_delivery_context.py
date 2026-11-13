"""What the composer sees when it decides whether an Inbox desk briefing reaches the user.

Regression for the live desk run whose briefing (FYI and Today sections) was answered
with SILENCE, "nothing new needs your attention", although the desk's Standing rule
says every briefing with content is delivered whole. The rule reached the decision;
it read as one more input that the routine-check default outweighed. No model runs
here: what is pinned is the request the real delivery path builds, from the report the
real todo delivery files to the call the real compose makes.
"""

from datetime import UTC, datetime
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import BaseMessage
import pytest

from app.agents.core.background import todo_run_delivery
from app.agents.core.background.run_report import RunOutcome
from app.agents.core.background.session import ExecutorRun, RunKind, TodoRun
from app.agents.core.graph_manager import GraphManager
from app.agents.prompts.todo_prompts import INBOX_DESK_DELIVERY_RULE
from app.constants.agents import OutcomeState
from app.constants.todos import INBOX_DESK_RECURRENCE, INBOX_DESK_TITLE
from app.db.repositories.outbox_items import outbox_items_repository
from app.db.repositories.outbox_messages import outbox_messages_repository
from app.models.outbox_models import OutboxItemDocument
from app.models.task_report_models import TaskReport
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType
from app.services.outbox import compose as compose_module
from app.services.outbox.compose import compose
from app.services.outbox.models import ComposeMode, ComposeResult, UrgencyClass
from app.services.outbox.router import InApp, Route
from app.services.tracked_todo_service import starting_canvas

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("real_tool_registry")]

USER = AuthenticatedUser(user_id="6812f0b3c9a14e2b7d5a91ce")
DESK = TodoDocument(
    id="66f838cc8829054e5f10e401",
    user_id=USER.user_id,
    title=INBOX_DESK_TITLE,
    notify_on_run=True,
    recurrence=INBOX_DESK_RECURRENCE,
    canvas_content=starting_canvas(INBOX_DESK_TITLE, [INBOX_DESK_DELIVERY_RULE]),
)
BRIEFING = "FYI: HDFC statement for September.\nToday: dentist at 16:00."
DEFAULTS = "Skip a routine check, a no-op, nothing new"
BINDING = (
    "come last and bind this decision above every default here, the skip rule included: "
    "when one asks to hear this todo's results, a report with content is told whole"
)
PASS_THROUGH = (
    "as a long-form deliverable with its headings and line items as written, in its order, "
    "with at most one line of your own before it, never retold as prose and never shortened."
)
SHORT_DEFAULT = "Say what the user needs first"


async def _filed_report() -> Any:
    """Return the report the desk's real delivery files for its briefing."""
    submit = AsyncMock()
    repo = MagicMock(get_by_id=AsyncMock(return_value=DESK))
    with (
        patch.object(todo_run_delivery, "todo_repository", repo),
        patch.object(todo_run_delivery, "record_run_finished", AsyncMock(return_value=True)),
        patch.object(todo_run_delivery, "record_executor_report", AsyncMock()),
        patch.object(todo_run_delivery, "submit", submit),
    ):
        await todo_run_delivery.deliver_todo_run_result(
            ExecutorRun(
                stream_id="s1",
                conversation_id="run-conv",
                user=USER,
                kind=RunKind.LIVE,
                task_id="t1",
                user_message_id=None,
            ),
            TodoRun(todo_id=DESK.id, trigger_type=TriggerType.SCHEDULED_TODO, runs_once=False),
            RunOutcome(report=TaskReport(outcome=OutcomeState.DONE), result=BRIEFING),
            BRIEFING,
            "final",
        )
    return submit.await_args.args[0]


async def _composer_input() -> tuple[str, dict[str, Any]]:
    """Return the system prompt and the item context the composer is handed for the desk's run."""
    report = await _filed_report()
    item = OutboxItemDocument(
        user_id=USER.user_id,
        report_id=report.report_id,
        report=report,
        urgency=UrgencyClass.BACKGROUND,
        mode=ComposeMode.UNSOLICITED,
        expires_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    seen: list[list[BaseMessage]] = []

    async def model(_schema: object, messages: list[BaseMessage], **_: object) -> ComposeResult:
        seen.append(messages)
        return ComposeResult.model_validate(
            {
                "dispositions": [
                    {"item_id": report.report_id, "action": "include", "reason": "whole"}
                ],
                "parts": [BRIEFING],
            }
        )

    graph = SimpleNamespace(aget_state=AsyncMock(return_value=SimpleNamespace(values={})))
    with (
        patch.object(compose_module, "ainvoke_structured", model),
        patch.object(GraphManager, "get_graph", AsyncMock(return_value=graph)),
        patch.object(outbox_messages_repository, "recent_sent", AsyncMock(return_value=[])),
        patch.object(
            outbox_items_repository,
            "list_settled_of_series",
            AsyncMock(return_value=[]),
        ),
    ):
        await compose(
            [item],
            user_id=USER.user_id,
            mode=ComposeMode.UNSOLICITED,
            destination=Route(
                alert_conversation_id="c", recorded_in=("c",), target=InApp(reason="no_chat_app")
            ),
            locale="en",
        )
    system, context = seen[0]
    return str(system.content), json.loads(str(context.content))


class TestTheDesksDeliveryRuleBindsTheDecision:
    async def test_the_rule_reaches_the_composer_with_the_briefing(self) -> None:
        _, context = await _composer_input()

        [item] = context["items"]
        assert f"- {INBOX_DESK_DELIVERY_RULE}" in item["guidance"]["standing_rules"]
        assert item["result"] == BRIEFING

    async def test_the_rules_are_binding_and_overrule_the_skip_default(self) -> None:
        system, _ = await _composer_input()

        assert BINDING in system

    async def test_the_rules_are_the_last_word_after_the_defaults(self) -> None:
        system, _ = await _composer_input()

        assert system.index(DEFAULTS) < system.index(BINDING)


class TestTheDesksBriefingKeepsItsSections:
    """Regression: comms retold a sectioned desk briefing as one prose paragraph under its "whole" rule."""

    async def test_a_whole_report_passes_through_with_its_headings_and_items(self) -> None:
        system, _ = await _composer_input()

        assert PASS_THROUGH in system

    async def test_the_pass_through_comes_after_the_keep_it_short_default(self) -> None:
        system, _ = await _composer_input()

        assert system.index(SHORT_DEFAULT) < system.index(PASS_THROUGH)
