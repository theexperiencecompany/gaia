"""The short reference a tool call is cited by in a finish_task report.

A provider's tool_call id rides in the API's call_id field, which the model cannot
quote. The ref is derived from that id, so the one shown with each tool result and the
one the review resolves a citation against agree with no state to keep in step.
"""

from hashlib import sha256

from langchain_core.messages import AnyMessage, ToolMessage

CALL_REF_PREFIX = "c"
CALL_REF_DIGITS = 6


def call_ref(tool_call_id: str) -> str:
    """Return the ref a tool call is cited by, derived from its provider-assigned id."""
    digest = sha256(tool_call_id.encode()).hexdigest()
    return f"{CALL_REF_PREFIX}{digest[:CALL_REF_DIGITS]}"


def with_call_ref(message: ToolMessage) -> ToolMessage:
    """Return the tool result as the executor model sees it: its ref on the first line."""
    header = f"[call {call_ref(message.tool_call_id)}]"
    if isinstance(message.content, str):
        return message.model_copy(update={"content": f"{header}\n{message.content}"})
    return message.model_copy(
        update={"content": [{"type": "text", "text": header}, *message.content]}
    )


def with_call_refs(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Return the messages with every tool result carrying its call ref."""
    return [with_call_ref(m) if isinstance(m, ToolMessage) else m for m in messages]
