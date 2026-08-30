"""Harness-owned completion: the executor cannot silently quit early.

``work_looks_unfinished`` is the prematurity check the executor's graph loop
runs before honouring a plain-text stop. True on a concrete "too shallow"
signal: a tracked todo still pending, fewer than ``COMPLETION_NON_WORK_TOOLS``
tools executed on a delegated task, or a final reply that PROMISES future work
("hang tight", "still digging") — nothing runs after the reply ends, so a
promise-to-continue is never a valid ending. Kept here so the graph builder
stays generic; only the executor opts in via
``create_agent(require_finish_to_end=True)``.

Everything here counts over ``current_delegation`` rather than the whole
thread, because the executor's thread spans every delegation of a conversation.
Counting the thread let delegation two inherit delegation one's tool calls and
nudges, so the guard fired exactly once per conversation and was dead for the
rest of it — the opposite of its purpose.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from app.agents.core.subagents.call_record import is_error_envelope, parsed_result
from app.constants.agents import (
    PLAYBOOK_CHECK_TAG,
    PLAYBOOK_DECISION_NUDGE_MESSAGE,
    PLAYBOOK_DECISION_TOOL_NAMES,
)
from app.constants.general import FINISH_TASK_NAME
from app.constants.llm import (
    COMPLETION_NON_WORK_TOOLS,
    COMPLETION_NUDGE_MESSAGE,
    COMPLETION_PROMISE_MARKERS,
)
from app.override.langgraph_bigtool.utils import State
from app.utils.multimodal import extract_text_content


def _is_completion_nudge(message: AnyMessage) -> bool:
    return isinstance(message, HumanMessage) and (
        extract_text_content(message.content) == COMPLETION_NUDGE_MESSAGE
    )


def _is_playbook_nudge(message: AnyMessage) -> bool:
    return isinstance(message, HumanMessage) and (
        extract_text_content(message.content) == PLAYBOOK_DECISION_NUDGE_MESSAGE
    )


def current_delegation(state: State) -> list[AnyMessage]:
    """The messages belonging to the delegation that is running right now.

    The executor keeps ONE thread per conversation (``executor_{thread_id}``),
    so a whole-history scan counts the PREVIOUS delegation's tool calls and
    nudges — and the guard switches itself off for every delegation after the
    first. The boundary is the newest genuine task turn: the ``HumanMessage``
    ``build_initial_messages`` appends per delegation. The clock message and
    the nudges themselves arrive as ``HumanMessage`` too, so all are skipped over.
    """
    messages = state.get("messages", [])
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, HumanMessage):
            continue
        if (
            message.additional_kwargs.get("time_context")
            or _is_completion_nudge(message)
            or _is_playbook_nudge(message)
        ):
            continue
        return list(messages[index:])
    return list(messages)


def completion_nudges_spent(state: State) -> int:
    """Nudges already injected into the CURRENT delegation."""
    return sum(1 for message in current_delegation(state) if _is_completion_nudge(message))


def reply_promises_future_work(state: State) -> bool:
    """True when the final reply commits to work that will never happen."""
    messages = state.get("messages", [])
    last = messages[-1] if messages else None
    if not isinstance(last, AIMessage):
        return False
    text = extract_text_content(last.content).lower()
    return any(marker in text for marker in COMPLETION_PROMISE_MARKERS)


def work_looks_unfinished(state: State) -> bool:
    """True when the executor's plain-text stop is not backed by completed work."""
    todos = state.get("todos") or []
    if any(isinstance(t, dict) and t.get("status") in ("pending", "in_progress") for t in todos):
        return True
    if reply_promises_future_work(state):
        return True
    # Nudge only when NOTHING real ran: discovery and errored calls prove no
    # work happened, but one successful real call ("send the email") must not
    # be second-guessed — the nudge's "do it now" can goad a duplicate send.
    completed_work = any(
        isinstance(m, ToolMessage)
        and m.status != "error"
        and m.name not in COMPLETION_NON_WORK_TOOLS
        for m in current_delegation(state)
    )
    return not completed_work


def _briefed(task_text: str) -> bool:
    """The brief opens a paragraph with the tag; the same string quoted inside a
    user's own request does not."""
    return any(line.strip() == PLAYBOOK_CHECK_TAG for line in task_text.splitlines())


def playbook_nudges_spent(state: State) -> int:
    """Decision nudges already injected into the CURRENT delegation."""
    return sum(1 for message in current_delegation(state) if _is_playbook_nudge(message))


def _is_stop(message: AnyMessage) -> bool:
    """A plain-text reply or a ``finish_task`` result: the executor's two ways
    to end a run. A tool-calling turn is not a stop; the run is still going."""
    if isinstance(message, AIMessage):
        return not message.tool_calls
    return isinstance(message, ToolMessage) and message.name == FINISH_TASK_NAME


def playbook_decision_pending(state: State) -> bool:
    """True when this delegation was briefed for a playbook decision and is
    stopping, in plain text or through ``finish_task``, without having made one.

    The brief is recognised by its tag on the task turn. A decision is a call
    to one of the decision tools whose result is not an error envelope: a
    refused ``write_playbook`` leaves the run exactly where it was, and the
    brief says so. Seen live: a briefed run that ended with ``finish_task`` and
    no decision was never nudged, so no decline was counted and the same brief
    came back on every later fire.
    """
    delegation = current_delegation(state)
    if not delegation:
        return False
    task, last = delegation[0], delegation[-1]
    if not isinstance(task, HumanMessage) or not _briefed(extract_text_content(task.content)):
        return False
    if not _is_stop(last):
        return False
    return not any(
        isinstance(m, ToolMessage)
        and m.name in PLAYBOOK_DECISION_TOOL_NAMES
        and m.status != "error"
        and not is_error_envelope(parsed_result(m))
        for m in delegation
    )
