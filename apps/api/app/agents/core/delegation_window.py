"""Which messages of an executor thread belong to the delegation running now.

The executor keeps ONE thread per conversation, so every check that counts
calls or nudges for "this run" slices it here first. A leaf on purpose: the
graph router, the middleware and the run's finalize all read it.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import AnyMessage, HumanMessage

from app.agents.context.slots import TIME_CONTEXT_MARKER, has_marker, is_conversation_summary
from app.constants.agents import (
    PLAYBOOK_DECISION_NUDGE_MESSAGE,
    REQUEST_AGENT_TAGS,
    leading_agent_tag,
)
from app.constants.llm import COMPLETION_NUDGE_MESSAGE
from app.override.langgraph_bigtool.utils import State
from app.utils.multimodal import extract_text_content


def is_completion_nudge(message: AnyMessage) -> bool:
    return isinstance(message, HumanMessage) and (
        extract_text_content(message.content) == COMPLETION_NUDGE_MESSAGE
    )


def is_playbook_nudge(message: AnyMessage) -> bool:
    return isinstance(message, HumanMessage) and (
        extract_text_content(message.content) == PLAYBOOK_DECISION_NUDGE_MESSAGE
    )


def _is_internal_payload(message: AnyMessage) -> bool:
    """Return whether the message frames a result or instruction, not a request."""
    tag = leading_agent_tag(extract_text_content(message.content))
    return tag is not None and tag not in REQUEST_AGENT_TAGS


def running_turn_start(messages: Sequence[AnyMessage]) -> int | None:
    """Index of the newest genuine request turn, or None when there is none.

    Skips the HumanMessages that are graph plumbing rather than a request: the
    clock, a conversation summary, the completion/playbook nudges, and internal
    result or instruction payloads.
    """
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, HumanMessage):
            continue
        if (
            has_marker(message, TIME_CONTEXT_MARKER)
            or is_conversation_summary(message)
            or is_completion_nudge(message)
            or is_playbook_nudge(message)
            or _is_internal_payload(message)
        ):
            continue
        return index
    return None


def current_delegation(state: State) -> list[AnyMessage]:
    """Return the messages belonging to the delegation that is running right now.

    The executor keeps ONE thread per conversation, so a whole-history scan
    would count the PREVIOUS delegation's tool calls and nudges; the boundary
    is running_turn_start.
    """
    messages = state.get("messages", [])
    start = running_turn_start(messages)
    return list(messages if start is None else messages[start:])
