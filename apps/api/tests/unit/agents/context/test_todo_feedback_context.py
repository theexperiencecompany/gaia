"""The user's feedback on a tracked todo: what each tier is shown so it can route and record it.

No model runs here, so its choice is not asserted. What is pinned is the prompt each
tier actually receives after its pre-model hooks: the comms turn answering a delivered
todo result sees the routing rule and the todo's id, and the executor that turn hands
the feedback to is bound to that todo and told where feedback lives.
"""

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
import pytest
from tests._harness.context_chain import ContextSeed, effective_context, message_in_slot, text_of
from tests._harness.context_sources import ContextSources

from app.agents.context.slots import PromptSlot
from app.agents.context.tiers import AgentTier
from app.models.todo_models import TodoDocument

pytestmark = pytest.mark.unit

DESK = TodoDocument(id="66f838cc8829054e5f10e401", user_id="user-alpha", title="Inbox desk")
DELIVERED = AIMessage(
    content=(
        f'[Delivered to the user on WhatsApp — result of tracked todo "Inbox desk" (id {DESK.id})]: '
        "Two need you today: Sam on the lease, and the Figma invoice."
    )
)
FEEDBACK = "stop showing me newsletters"


async def _comms_reply_to_the_delivery() -> list[AnyMessage]:
    return await effective_context(
        AgentTier.COMMS,
        ContextSeed(query=FEEDBACK, prior_messages=[HumanMessage(content="hey"), DELIVERED]),
    )


class TestTheCommsTurnAnsweringADeliveredResult:
    async def test_its_static_prompt_routes_the_feedback_to_the_todo(self) -> None:
        static = text_of(message_in_slot(await _comms_reply_to_the_delivery(), PromptSlot.STATIC))

        assert "FEEDBACK ON A TRACKED TODO IS APPLIED:" in static
        assert (
            "call_executor(active_todo_id=<that todo's id>, "
            'task="Apply the user\'s feedback to this todo: <their words>")'
        ) in static

    async def test_the_delivered_result_with_its_todo_id_precedes_the_reply(self) -> None:
        texts = [text_of(message) for message in await _comms_reply_to_the_delivery()]

        assert texts.index(DELIVERED.content) < texts.index(FEEDBACK)


class TestTheExecutorApplyingTheFeedback:
    async def _context(self) -> str:
        messages = await effective_context(
            AgentTier.EXECUTOR,
            ContextSeed(
                query=f"Apply the user's feedback to this todo: {FEEDBACK}",
                sources=ContextSources(active_todo=DESK),
                configurable_overrides={"active_todo_id": DESK.id},
            ),
        )
        return "\n".join(text_of(message) for message in messages)

    async def test_it_is_bound_to_the_todo_and_told_to_obey_its_rules(self) -> None:
        context = await self._context()

        assert f"🎯 ACTIVE TODO (this run is bound to this todo)\n   id: {DESK.id}\n" in context
        assert "Its Standing rules are the user's instructions for this todo" in context

    async def test_it_is_told_where_each_kind_of_feedback_lives(self) -> None:
        context = await self._context()

        assert "THE USER'S FEEDBACK ON A TODO" in context
        assert 'one line in its canvas.md "## Standing rules"' in context
        assert "update_integration_instructions" in context
        assert "update_tracked_todo's recurrence or scheduled_at" in context
