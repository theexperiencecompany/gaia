"""What the comms model sees when it decides whether an Inbox desk briefing reaches the user.

Regression for the live desk run whose briefing (FYI and Today sections) was answered
with SILENCE, "nothing new needs your attention", although the desk's Standing rule
says every briefing with content is delivered whole. The rule reached the decision;
it read as one more input that the routine-check default outweighed. No model runs
here: what is pinned is the request the step builds for the run, after comms'
pre-model hooks.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AnyMessage, HumanMessage
import pytest
from tests._harness.context_chain import ContextSeed, effective_context, text_of
from tests.unit.services.conversation.log_helpers import todo_run as typed_todo_run

from app.agents.context.tiers import AgentTier
from app.agents.core.background import todo_run_delivery
from app.agents.prompts.todo_prompts import INBOX_DESK_DELIVERY_RULE
from app.constants.conversation import WORK_DONE_NOTE
from app.constants.todos import INBOX_DESK_RECURRENCE, INBOX_DESK_TITLE
from app.models.todo_models import TodoDocument
from app.services.tracked_todo_service import starting_canvas

pytestmark = pytest.mark.unit

USER_ID = "6812f0b3c9a14e2b7d5a91ce"
DESK = TodoDocument(
    id="66f838cc8829054e5f10e401",
    user_id=USER_ID,
    title=INBOX_DESK_TITLE,
    notify_on_run=True,
    recurrence=INBOX_DESK_RECURRENCE,
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
    """Build what the step hands comms for the desk's run: its write-up note, then the finished work."""
    repo = MagicMock(get_by_id=AsyncMock(return_value=DESK))
    run = typed_todo_run().model_copy(
        update={"todo_id": DESK.id, "title": DESK.title, "runs_once": False}
    )
    with patch.object(todo_run_delivery, "todo_repository", repo):
        note = await todo_run_delivery.write_up_note(run)
    return HumanMessage(content=f"{note}\n{WORK_DONE_NOTE.format(report=BRIEFING)}")


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
