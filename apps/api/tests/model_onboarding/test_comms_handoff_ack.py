"""Onboarding gate: does comms acknowledge a hand-off in a few words, even after the instant reaction?

Run it before changing COMMS_MODEL_NAME or the comms prompt's hand-off rules:
uv run pytest tests/model_onboarding/test_comms_handoff_ack.py -m model_onboarding
Needs OPENAI_API_KEY (or COMMS_EVAL_VIA_OPENROUTER=1). Two model calls per case: the
model's own call_executor for the request, then the step right after the hand-off.
"""

from typing import Any, cast

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest

from app.agents.core.graph_builder.build_graph import comms_tools
from app.agents.core.messages import MessageScope
from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from app.agents.tools.executor_tool import handoff_message
from app.constants.comms import REACT_TOOL_NAME, STAY_SILENT_TOOL_NAME
from app.constants.conversation import MESSAGE_HANDLE, REACTION_NOTE
from app.constants.general import CALL_EXECUTOR_NAME
from tests._harness.context_chain import comms_turn_messages
from tests.model_onboarding.test_comms_executor_status import _model

pytestmark = [pytest.mark.model_onboarding]

REPEATS = 3
TASK_ID = "7b2e91"
REQUEST = "add renew my passport to my todos for friday"
#: Longer than this is a restatement or a preview, not an acknowledgement.
ACK_MAX_CHARS = 80


async def _after_hand_off(source: str, reacted: str | None) -> AIMessage:
    """Return the model's step right after its own hand-off of REQUEST."""
    model = _model().bind_tools(list(comms_tools().values()))
    config: Any = {"configurable": {"thread_id": f"conv-ack-{source}"}}
    built = await comms_turn_messages(
        query=f"{MESSAGE_HANDLE.format(seq=1)}{REQUEST}", scope=MessageScope(source=source)
    )
    if reacted is not None:
        at = next(i for i, message in enumerate(built) if REQUEST in str(message.content))
        built.insert(at + 1, HumanMessage(content=REACTION_NOTE.format(emoji=reacted)))
    ordered = manage_system_prompts_node(cast(Any, {"messages": built}), config, None)
    first = cast(AIMessage, await model.ainvoke(ordered["messages"]))
    calls = [call for call in first.tool_calls if call["name"] == CALL_EXECUTOR_NAME]
    if not calls:
        pytest.fail(f"the model did not dispatch the request: {first.content!r}")
    thread = [
        *built,
        AIMessage(content="", tool_calls=[calls[0]]),
        ToolMessage(content=handoff_message(TASK_ID), tool_call_id=calls[0]["id"]),
    ]
    ordered = manage_system_prompts_node(cast(Any, {"messages": thread}), config, None)
    return cast(AIMessage, await model.ainvoke(ordered["messages"]))


@pytest.mark.parametrize("attempt", range(REPEATS))
@pytest.mark.parametrize("reacted", [None, "👀"])
@pytest.mark.parametrize("source", ["web", "telegram"])
async def test_a_hand_off_gets_a_few_words_of_acknowledgement(
    source: str, reacted: str | None, attempt: int
) -> None:
    step = await _after_hand_off(source, reacted)

    text = step.text.strip()
    assert 0 < len(text) <= ACK_MAX_CHARS, step
    assert not {call["name"] for call in step.tool_calls} & {
        REACT_TOOL_NAME,
        STAY_SILENT_TOOL_NAME,
        CALL_EXECUTOR_NAME,
    }
