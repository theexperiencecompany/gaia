"""The repair rewrites polluted comms replies in place and removes the ones with nothing left."""

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from scripts.repair_comms_message_breaks import repair_writes

from app.constants.general import NEW_MESSAGE_BREAKER
from app.override.langgraph_bigtool.utils import messages_delta_reducer

BR = NEW_MESSAGE_BREAKER
CALL = [{"name": "call_executor", "args": {"task": "x"}, "id": "tc-1"}]


def test_a_tool_call_with_only_breaks_keeps_its_id_and_loses_the_breaks() -> None:
    [write] = repair_writes([AIMessage(id="a1", content=BR * 13, tool_calls=CALL)])
    assert isinstance(write, AIMessage)
    assert (write.id, write.content, write.tool_calls[0]["id"]) == ("a1", "", "tc-1")


def test_a_reply_with_only_breaks_is_removed() -> None:
    assert repair_writes([AIMessage(id="a2", content=BR * 3998 + "<NEW_MESSAGE_BREAK")]) == [
        RemoveMessage(id="a2")
    ]


def test_text_and_clean_messages_are_left_alone_or_trimmed() -> None:
    writes = repair_writes(
        [
            HumanMessage(id="h1", content=f"{BR}{BR}"),
            AIMessage(id="a3", content="already clean"),
            AIMessage(id="a4", content=f"on it{BR * 14}"),
        ]
    )
    assert [(w.id, w.content) for w in writes] == [("a4", "on it")]


def test_the_writes_replace_and_remove_through_the_real_reducer() -> None:
    history = [
        HumanMessage(id="h1", content="go"),
        AIMessage(id="a1", content=BR * 13, tool_calls=CALL),
        AIMessage(id="a2", content=BR * 3998),
    ]
    repaired = messages_delta_reducer(history, [repair_writes(history)])
    assert [(m.id, m.content) for m in repaired] == [("h1", "go"), ("a1", "")]
