"""Harness-owned completion: the executor cannot silently quit early.

work_looks_unfinished is the prematurity check run before honouring a
plain-text stop: true on a pending todo, too few real tool calls, or a
reply that PROMISES future work. Only the executor opts in via
create_agent(require_finish_to_end=True).

Everything here counts over current_delegation, not the whole thread: the
executor's thread spans every delegation, and counting the thread let
delegation two inherit delegation one's tool calls, so the guard fired once
per conversation and stayed dead after.
"""

from __future__ import annotations

from typing import TypedDict, cast

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from app.agents.core.delegation_window import (
    current_delegation,
    is_completion_nudge,
    is_playbook_nudge,
)
from app.agents.core.outcome_review import is_successful_work
from app.agents.core.subagents.call_record import is_error_envelope, parsed_result
from app.constants.agents import PLAYBOOK_CHECK_TAG, PLAYBOOK_DECISION_TOOL_NAMES
from app.constants.general import FINISH_TASK_NAME
from app.constants.llm import COMPLETION_PROMISE_MARKERS
from app.override.langgraph_bigtool.utils import State
from app.utils.multimodal import extract_text_content


def completion_nudges_spent(state: State) -> int:
    """Nudges already injected into the CURRENT delegation."""
    return sum(1 for message in current_delegation(state) if is_completion_nudge(message))


def reply_promises_future_work(state: State) -> bool:
    """Return whether the final reply commits to work that will never happen."""
    messages = state.get("messages", [])
    last = messages[-1] if messages else None
    if not isinstance(last, AIMessage):
        return False
    text = extract_text_content(last.content).lower()
    return any(marker in text for marker in COMPLETION_PROMISE_MARKERS)


class _TodoEntry(TypedDict, total=False):
    """The one todo field the prematurity check reads."""

    status: str


def _todo_is_open(todo: object) -> bool:
    if not isinstance(todo, dict):
        return False
    entry: _TodoEntry = cast("_TodoEntry", todo)
    return entry.get("status") in ("pending", "in_progress")


def work_looks_unfinished(state: State) -> bool:
    """Return whether the executor's plain-text stop is not backed by completed work."""
    todos = state.get("todos") or []
    if any(_todo_is_open(t) for t in todos):
        return True
    if reply_promises_future_work(state):
        return True
    # Nudge only when NOTHING real ran: discovery and errored calls prove no
    # work happened, but one successful real call ("send the email") must not
    # be second-guessed — the nudge's "do it now" can goad a duplicate send.
    return not any(is_successful_work(m) for m in current_delegation(state))


def _briefed(task_text: str) -> bool:
    """Return whether the brief opens a paragraph with the tag.

    The same string quoted inside a user's own request does not.
    """
    return any(line.strip() == PLAYBOOK_CHECK_TAG for line in task_text.splitlines())


def playbook_nudges_spent(state: State) -> int:
    """Decision nudges already injected into the CURRENT delegation."""
    return sum(1 for message in current_delegation(state) if is_playbook_nudge(message))


def _is_stop(message: AnyMessage) -> bool:
    """Return whether this is a plain-text reply or a finish_task result.

    The executor's two ways to end a run. A tool-calling turn is not a stop.
    """
    if isinstance(message, AIMessage):
        return not message.tool_calls
    return isinstance(message, ToolMessage) and message.name == FINISH_TASK_NAME


def playbook_decision_pending(state: State) -> bool:
    """Return whether this delegation was briefed but is stopping without a decision.

    The brief is recognised by its tag on the task turn. A decision is a
    call to a decision tool whose result is not an error envelope — a
    refused write_playbook leaves the run exactly where it was.
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
