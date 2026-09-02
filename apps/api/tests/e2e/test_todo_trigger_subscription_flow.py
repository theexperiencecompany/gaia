"""E2E: subscribing a tracked todo to a trigger, through a real compiled graph.

WHAT THIS TESTS (REAL GAIA CODE):
- ``list_trigger_fields`` / ``subscribe_todo_to_trigger`` from
  ``app.agents.tools.tracked_todo_tools`` — the real tools, bound into a real
  compiled agent graph.
- The real matchable-fields catalog and the real deterministic validator: the
  model writes a camelCased field name, and the repair path resolves it without
  any second LLM call.
- ``create_agent`` from ``app.override.langgraph_bigtool.create_agent`` compiles
  the graph; the real pre-model hooks run.

The point of driving it here rather than calling the tool directly is the loop:
a rejection has to be something the *next model turn* can act on. A unit test can
assert the error text; only running the loop shows the model gets a second turn
with the catalog in front of it.

Mock surfaces:
- LLM: BindableToolsFakeModel (scripted tool calls)
- Composio registration + Mongo: mocked at the service seam
- Store: InMemoryStore, Checkpointer: MemorySaver

DELETE ``app/services/triggers/matchable_fields.py`` → these tests FAIL.
DELETE the validator's mechanical repair → the typo test FAILS.
"""

from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest

from app.agents.tools.tracked_todo_tools import (
    list_trigger_fields,
    subscribe_todo_to_trigger,
)
from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
)
from tests.e2e.conftest import build_gaia_test_graph
from tests.helpers import BindableToolsFakeModel

_SERVICE = "app.services.triggers.subscription_service"
USER_ID = "507f1f77bcf86cd799439011"
TODO_ID = "todo-e2e"
GMAIL = "gmail_new_message"


def _tool_message(messages: list, call_id: str) -> ToolMessage:
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.tool_call_id == call_id:
            return msg
    raise AssertionError(f"No ToolMessage for {call_id!r}")


def _todo() -> TodoDocument:
    return TodoDocument.model_validate(
        {"id": TODO_ID, "user_id": USER_ID, "title": "Chase Acme about the invoice"}
    )


@pytest.mark.e2e
class TestSubscribeThroughTheGraph:
    @staticmethod
    def _registry() -> dict:
        return {
            list_trigger_fields.name: list_trigger_fields,
            subscribe_todo_to_trigger.name: subscribe_todo_to_trigger,
        }

    async def _run(self, script, thread_config, in_memory_store, memory_saver):
        fake_llm = BindableToolsFakeModel(responses=script)
        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry=self._registry(),
            initial_tool_ids=list(self._registry()),
            checkpointer=memory_saver,
            store=in_memory_store,
        )
        config = {
            **thread_config,
            "configurable": {**thread_config["configurable"], "user_id": USER_ID},
            "metadata": {"user_id": USER_ID},
        }
        state = await graph.ainvoke(
            {"messages": [HumanMessage(content="Watch for Acme's reply on this todo.")]},
            config=config,
        )
        return state["messages"]

    async def test_a_typod_field_is_repaired_and_the_subscription_registers(
        self, thread_config, in_memory_store, memory_saver
    ):
        """The model writes ``threadId``; the catalog says ``thread_id``.

        No LLM repair pass runs — the deterministic stage resolves it, and the
        tool reports what it changed so the model does not repeat the mistake.
        """
        script = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "subscribe_todo_to_trigger",
                        "args": {
                            "todo_id": TODO_ID,
                            "trigger_name": GMAIL,
                            "action": "execute",
                            "conditions": [
                                {
                                    "field_name": "threadId",
                                    "operator": "equals",
                                    "value": "18c9f0a1",
                                }
                            ],
                        },
                        "id": "call-sub",
                    }
                ],
            ),
            AIMessage(content="That todo is now watching the thread."),
        ]

        update = AsyncMock(return_value=None)
        with (
            patch(
                f"{_SERVICE}.todo_repository",
                get=AsyncMock(return_value=_todo()),
                update=update,
            ),
            patch(
                f"{_SERVICE}.TriggerService",
                register_triggers=AsyncMock(return_value=[]),
                unregister_triggers=AsyncMock(return_value=True),
            ),
            patch(f"{_SERVICE}.capture_event"),
        ):
            messages = await self._run(script, thread_config, in_memory_store, memory_saver)

        result = _tool_message(messages, "call-sub")
        assert "is now watching" in result.content
        assert "Repaired automatically" in result.content

        stored = update.await_args.kwargs["update"].trigger_subscriptions[0]
        assert stored.conditions[0].field_name == "thread_id"
        assert stored.action is SubscriptionAction.EXECUTE
        # Gmail registers no per-todo instance, so dispatch must find it by user.
        assert stored.resolution is SubscriptionResolution.ACCOUNT

    async def test_a_rejection_gives_the_next_turn_the_catalog_to_retry_from(
        self, thread_config, in_memory_store, memory_saver
    ):
        """The model invents a field, is refused, and its second turn succeeds.

        This is the repair loop: the agent loop is the pass, and the catalog in
        the error is what makes the retry right rather than another guess.
        """
        script = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "subscribe_todo_to_trigger",
                        "args": {
                            "todo_id": TODO_ID,
                            "trigger_name": GMAIL,
                            "action": "execute",
                            "conditions": [
                                {
                                    "field_name": "recipient_domain",
                                    "operator": "equals",
                                    "value": "acme.com",
                                }
                            ],
                        },
                        "id": "call-bad",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "subscribe_todo_to_trigger",
                        "args": {
                            "todo_id": TODO_ID,
                            "trigger_name": GMAIL,
                            "action": "execute",
                            "conditions": [
                                {
                                    "field_name": "sender",
                                    "operator": "contains",
                                    "value": "acme.com",
                                }
                            ],
                        },
                        "id": "call-good",
                    }
                ],
            ),
            AIMessage(content="Watching for anything from acme.com."),
        ]

        update = AsyncMock(return_value=None)
        with (
            patch(
                f"{_SERVICE}.todo_repository",
                get=AsyncMock(return_value=_todo()),
                update=update,
            ),
            patch(
                f"{_SERVICE}.TriggerService",
                register_triggers=AsyncMock(return_value=[]),
                unregister_triggers=AsyncMock(return_value=True),
            ),
            patch(f"{_SERVICE}.capture_event"),
        ):
            messages = await self._run(script, thread_config, in_memory_store, memory_saver)

        refusal = _tool_message(messages, "call-bad")
        assert "Could not subscribe" in refusal.content
        # The refusal has to carry the real fields, or the retry is another guess.
        assert "thread_id" in refusal.content
        assert "sender" in refusal.content

        accepted = _tool_message(messages, "call-good")
        assert "is now watching" in accepted.content
        assert (
            update.await_args.kwargs["update"].trigger_subscriptions[0].conditions[0].field_name
            == "sender"
        )

    async def test_the_model_can_ask_what_a_trigger_delivers_first(
        self, thread_config, in_memory_store, memory_saver
    ):
        script = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "list_trigger_fields",
                        "args": {"trigger_name": GMAIL},
                        "id": "call-fields",
                    }
                ],
            ),
            AIMessage(content="Gmail gives me thread_id, sender, subject and more."),
        ]

        messages = await self._run(script, thread_config, in_memory_store, memory_saver)

        catalog = _tool_message(messages, "call-fields")
        assert "thread_id (string)" in catalog.content
        assert "Not matchable:" in catalog.content
