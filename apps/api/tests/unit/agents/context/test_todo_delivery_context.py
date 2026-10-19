"""What the comms model sees when it decides whether an Inbox desk briefing reaches the user.

Regression for the live desk run whose briefing (FYI and Today sections) was answered
with SILENCE, "nothing new needs your attention", although the desk's Standing rule
says every briefing with content is delivered whole. The rule reached the decision;
it read as one more input that the routine-check default outweighed. No model runs
here: what is pinned is the request the real delivery path builds, after comms'
pre-model hooks.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AnyMessage, HumanMessage
import pytest
from tests._harness.context_chain import ContextSeed, effective_context, text_of

from app.agents.context.tiers import AgentTier
from app.agents.core.background import comms_narrator, todo_run_delivery
from app.agents.core.background.session import ExecutorRun, RunKind, TodoRun
from app.agents.prompts.todo_prompts import INBOX_DESK_DELIVERY_RULE
from app.constants.todos import INBOX_DESK_TITLE
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType
from app.services.tracked_todo_service import starting_canvas

pytestmark = pytest.mark.unit

USER = AuthenticatedUser(user_id="6812f0b3c9a14e2b7d5a91ce")
DESK = TodoDocument(
    id="66f838cc8829054e5f10e401",
    user_id=USER.user_id,
    title=INBOX_DESK_TITLE,
    notify_on_run=True,
    canvas_content=starting_canvas(INBOX_DESK_TITLE, [INBOX_DESK_DELIVERY_RULE]),
)
BRIEFING = "FYI: HDFC statement for September.\nToday: dentist at 16:00."
DEFAULTS = "Anything else is not worth a message"
BINDING = (
    "They bind this decision above every default here and in your instructions, the "
    "SILENCE rule included: when one asks to hear this todo's results, a report with "
    "content is sent whole"
)
PASS_THROUGH = (
    "a long-form deliverable: its headings and line items as written, in its order, with "
    "at most one line of your own before it, never retold as prose and never shortened."
)
SHORT_DEFAULT = "keep it short"


async def _delivered_request() -> HumanMessage:
    """Run the desk's real delivery up to the comms call and return the message it hands comms."""
    graph_run = AsyncMock(return_value=("<SILENCE>nothing new</SILENCE>", []))
    repo = MagicMock(get_by_id=AsyncMock(return_value=DESK))
    with (
        patch.object(todo_run_delivery, "todo_repository", repo),
        patch.object(todo_run_delivery, "record_run_finished", AsyncMock(return_value=True)),
        patch.object(todo_run_delivery, "capture", MagicMock()),
        patch.object(comms_narrator.GraphManager, "get_graph", AsyncMock()),
        patch.object(
            comms_narrator, "build_agent_config", AsyncMock(return_value={"configurable": {}})
        ),
        patch.object(comms_narrator, "execute_graph_silent", graph_run),
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
            TodoRun(todo_id=DESK.id, trigger_type=TriggerType.SCHEDULED_TODO),
            BRIEFING,
            "final",
        )
    (message,) = graph_run.await_args.args[1]["messages"]
    return message


async def _comms_context() -> str:
    request = await _delivered_request()
    messages: list[AnyMessage] = await effective_context(
        AgentTier.COMMS, ContextSeed(query=text_of(request))
    )
    return "\n".join(text_of(message) for message in messages)


class TestTheDesksDeliveryRuleBindsTheDecision:
    async def test_the_rule_reaches_comms_with_the_briefing(self) -> None:
        context = await _comms_context()

        assert f"- {INBOX_DESK_DELIVERY_RULE}" in context
        assert BRIEFING in context

    async def test_the_rules_are_binding_and_overrule_the_silence_default(self) -> None:
        context = await _comms_context()

        assert BINDING in context

    async def test_the_rules_are_the_last_word_after_the_defaults(self) -> None:
        context = await _comms_context()

        assert context.index(DEFAULTS) < context.index(f"- {INBOX_DESK_DELIVERY_RULE}")


class TestTheDesksBriefingKeepsItsSections:
    """Regression: comms retold a sectioned desk briefing as one prose paragraph under its "whole" rule."""

    async def test_a_whole_report_passes_through_with_its_headings_and_items(self) -> None:
        context = await _comms_context()

        assert PASS_THROUGH in context

    async def test_the_pass_through_comes_after_the_keep_it_short_default(self) -> None:
        context = await _comms_context()

        assert context.index(SHORT_DEFAULT) < context.index(PASS_THROUGH)
