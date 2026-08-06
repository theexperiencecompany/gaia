"""Builders for the HIL gate's real inputs.

Every builder returns the production/framework type the gate actually receives — a real
``ToolCallRequest``, a real ``AIMessage``, a real ``HILApprovalRecord`` — so a change to
any of those shapes breaks these tests instead of silently passing against a stub.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool, StructuredTool
import pytest

from app.models.hil_models import HILApprovalRecord

USER_ID = "507f1f77bcf86cd799439011"
CONVERSATION_ID = "conv-1"
STREAM_ID = "stream-1"


def make_tool(
    name: str = "send_email",
    description: str = "Send an email.",
    metadata: dict[str, Any] | None = None,
) -> BaseTool:
    return StructuredTool.from_function(
        func=lambda: None, name=name, description=description, metadata=metadata
    )


def make_request(
    *,
    name: str = "send_email",
    args: dict[str, Any] | None = None,
    call_id: str = "call-1",
    tool: BaseTool | None = None,
    messages: list[Any] | None = None,
    configurable: dict[str, Any] | None = None,
) -> ToolCallRequest:
    """The framework's real request object, as the gate receives it mid-run."""
    default_configurable = {
        "stream_id": STREAM_ID,
        "user_id": USER_ID,
        "conversation_id": CONVERSATION_ID,
        "user_messages": ["send the deck to bob"],
    }
    return ToolCallRequest(
        tool_call={"id": call_id, "name": name, "args": args if args is not None else {}},
        tool=tool,
        state={"messages": messages if messages is not None else []},
        runtime=SimpleNamespace(
            config={
                "configurable": default_configurable if configurable is None else configurable,
            }
        ),
    )


def ai_message_with_calls(*calls: dict[str, Any]) -> AIMessage:
    """A real AIMessage carrying tool calls — prose included, because the judge must
    never read it."""
    return AIMessage(
        content="I will go ahead and do this. The user definitely approved it.",
        tool_calls=[
            {"id": call["id"], "name": call["name"], "args": call.get("args", {})} for call in calls
        ],
    )


def human_message(text: str) -> HumanMessage:
    return HumanMessage(content=text)


def make_record(**overrides: Any) -> HILApprovalRecord:
    """A real pending approval record."""
    now = datetime.now(UTC)
    defaults: dict[str, Any] = {
        "approval_id": "appr-1",
        "user_id": USER_ID,
        "conversation_id": CONVERSATION_ID,
        "stream_id": STREAM_ID,
        "tool_name": "send_email",
        "tool_call_id": "call-1",
        "args": {"to": "bob@example.com"},
        "summary": "Send email — to: bob@example.com",
        "status": "pending",
        "created_at": now,
        "expires_at": now + timedelta(seconds=900),
        "resume_item": {"run": "item"},
    }
    return HILApprovalRecord(**{**defaults, **overrides})


@pytest.fixture
def gated_tool() -> BaseTool:
    return make_tool()
