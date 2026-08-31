"""Resolve pending HIL approvals from a bot user's next chat reply.

BUTTON-LESS CHANNELS ONLY. The caller (``app/services/chat/stream.py``,
``_resolve_pending_approval_turn``) invokes this EXCLUSIVELY for messaging-platform
bots — WhatsApp, Telegram, Slack, Discord. Web/mobile/desktop render real
Approve/Deny buttons and resolve deterministically via ``POST
/approvals/{id}/decision``; they never run this classifier, because asking an LLM
to guess intent when an unambiguous button already exists is needless risk. A
typed reply is the ONLY approval surface a text-only bot has, so here — and only
here — one fast LLM call classifies it.

Single pending approval → approve / deny / unrelated:
  - approve resolves it and resumes the paused run (runs the tool AS PROPOSED);
  - deny resolves it as a refusal, carrying any correction/redirect as feedback
    for the model (the redirect is next-turn context, not executed now);
  - unrelated abandons it (resumed as a refusal so the run wraps up instead of
    racing the new turn) and lets the new message run as a normal turn.

An 'approve' means run the action EXACTLY as proposed — there is no arg-editing.
A reply that accepts but changes anything ("yes but cc finance") is a deny with
the change as feedback, so the agent re-proposes rather than silently running the
wrong action (enforced by the prompt and by ``_no_arg_edit``).

Several approvals pending (a wait_for_subagents batch) → per-item approve / deny /
leave against the numbered list: "yes" approves all, "no" declines all; a
selective reply decides only what it names. Unnamed actions are DENIED when the
reply is exclusive ("just the email") and LEFT pending when it is a non-exclusive
partial ("approve the email"), so a bot user answering across several messages
isn't force-declined on the ones they haven't reached. An item left 'leave' stays
pending for a later reply or the timeout sweep.

Context given to the classifier: the pending action(s) rendered with full
(bounded) args plus a short window of recent turns — see ``build_action_detail``
and the caller's ``_recent_history``. It fails safe: an LLM error leaves approvals
pending, never approves.
"""

import contextlib
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.llm.client import StructuredCallOptions, ainvoke_structured, silent_metered_config
from app.constants.hil import (
    HIL_CLASSIFIER_MAX_ARG_CHARS,
    HIL_CLASSIFIER_MAX_DETAIL_CHARS,
    HIL_LLM_TIMEOUT_SECONDS,
)
from app.constants.log_tags import LogTag
from app.models.hil_models import HILApprovalRecord
from app.models.message_models import MessageDict
from app.services.hil.approvals_store import list_pending_for_conversation
from app.services.hil.bridge import build_action_detail
from app.services.hil.resolution import (
    ApprovalRequestForbiddenError,
    ApprovalRequestNotFoundError,
    abandon_conversation_approvals,
    resolve_approval,
)
from app.utils.general_utils import clip_text
from shared.py.wide_events import log

DecisionAction = Literal["approve", "deny", "unrelated"]

# Auto-deny reason when the user moves on without answering the approval.
UNRELATED_FEEDBACK = "The user moved on to a different request; do not perform the action."


class DecisionResult(BaseModel):
    """LLM classification of a user's reply to a pending approval."""

    action: DecisionAction
    feedback: str | None = None


class BatchItemDecision(BaseModel):
    """One pending action's verdict from the user's reply."""

    index: int = Field(description="1-based index of the pending action")
    action: Literal["approve", "deny", "leave"]
    feedback: str | None = None


class BatchDecisionResult(BaseModel):
    """LLM classification of a reply against several pending approvals."""

    unrelated: bool = Field(
        description="True when the message is a new request, not an answer to the pending actions"
    )
    decisions: list[BatchItemDecision] = Field(default_factory=list)


async def resolve_pending_from_message(
    conversation_id: str,
    user_id: str,
    message: str,
    history: list[MessageDict] | None = None,
) -> DecisionAction | None:
    """Resolve the conversation's pending approval(s) from ``message``.

    ``history`` is a recent window of prior turns (context for the classifier).
    Returns the overall classified action ("approve" when anything was approved,
    "deny" when things were only declined, "unrelated" when the user moved on),
    or ``None`` when nothing was pending or the reply addressed none of it.
    """
    pending = await list_pending_for_conversation(conversation_id)
    if not pending:
        return None
    if len(pending) == 1:
        return await _resolve_single(pending[0], conversation_id, user_id, message, history)
    return await _resolve_batch(pending, conversation_id, user_id, message, history)


async def _resolve_single(
    record: HILApprovalRecord,
    conversation_id: str,
    user_id: str,
    message: str,
    history: list[MessageDict] | None,
) -> DecisionAction | None:
    action_detail = build_action_detail(record.summary, record.args)
    result = await interpret_decision_message(message, [action_detail], history, user_id=user_id)
    if result is None:
        # The classifier errored. Leave the approval pending rather than abandon it —
        # a transient hiccup must not silently decline a legitimate pending action
        # (matches the batch path's fail-toward-pending behavior).
        return None
    if result.action == "unrelated":
        # The user moved on. Abandon the paused run so it resumes, sees a refusal,
        # wraps up, and frees the conversation's executor lock for the new turn.
        await abandon_conversation_approvals(conversation_id, user_id, UNRELATED_FEEDBACK)
        return "unrelated"

    action, feedback = _no_arg_edit(result.action, result.feedback)
    await _safe_resolve(record.approval_id, user_id, action, feedback)
    return action


async def _resolve_batch(
    pending: list[HILApprovalRecord],
    conversation_id: str,
    user_id: str,
    message: str,
    history: list[MessageDict] | None,
) -> DecisionAction | None:
    """Apply a per-item classification of ``message`` to the pending batch.

    Decisions dispatch through ``resolve_approval`` one by one; the per-conversation
    resume slot ensures only the first actually re-dispatches the executor — the
    join round it wakes collects the rest.
    """
    action_details = [build_action_detail(r.summary, r.args) for r in pending]
    result = await interpret_batch_decision_message(
        message, action_details, history, user_id=user_id
    )
    if result.unrelated:
        await abandon_conversation_approvals(conversation_id, user_id, UNRELATED_FEEDBACK)
        return "unrelated"

    approved = denied = 0
    for decision in result.decisions:
        if decision.action == "leave" or not 1 <= decision.index <= len(pending):
            continue
        record = pending[decision.index - 1]
        action, feedback = _no_arg_edit(decision.action, decision.feedback)
        await _safe_resolve(record.approval_id, user_id, action, feedback)
        if action == "approve":
            approved += 1
        else:
            denied += 1

    if approved:
        return "approve"
    if denied:
        return "deny"
    return None


async def interpret_batch_decision_message(
    message: str,
    action_details: list[str],
    history: list[MessageDict] | None = None,
    *,
    user_id: str,
) -> BatchDecisionResult:
    """Classify a chat reply against several pending approvals, per item.

    Fails toward leaving everything pending (empty decisions, not unrelated) —
    never toward acting, and never toward abandoning on an LLM hiccup.
    """
    try:
        return await ainvoke_structured(
            BatchDecisionResult,
            _batch_prompt(message, action_details, history),
            label="hil_conversational_resolve_batch",
            config=silent_metered_config(user_id),
            options=StructuredCallOptions(timeout=HIL_LLM_TIMEOUT_SECONDS),
        )
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} Batch conversational resolve failed, leaving pending",
            error=str(e),
            error_type=type(e).__name__,
        )
        return BatchDecisionResult(unrelated=False)


async def interpret_decision_message(
    message: str,
    action_details: list[str],
    history: list[MessageDict] | None = None,
    *,
    user_id: str,
) -> DecisionResult | None:
    """Classify a chat reply against pending approvals.

    ``None`` on an LLM error, so the caller leaves the approval pending — never toward
    silently executing an action, and never toward abandoning a legitimate one on a
    transient hiccup (an error is not the same signal as a genuine ``unrelated``)."""
    try:
        return await ainvoke_structured(
            DecisionResult,
            _prompt(message, action_details, history),
            label="hil_conversational_resolve",
            config=silent_metered_config(user_id),
            options=StructuredCallOptions(timeout=HIL_LLM_TIMEOUT_SECONDS),
        )
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} Conversational resolve failed, leaving pending",
            error=str(e),
            error_type=type(e).__name__,
        )
        return None


# --- internals -----------------------------------------------------------------


def _no_arg_edit(
    action: Literal["approve", "deny"], feedback: str | None
) -> tuple[Literal["approve", "deny"], str | None]:
    """An approval can't carry an instruction — the gate runs the tool with its
    ORIGINAL args, there is no arg-editing. So an 'approve' that arrived with
    feedback is a modification we would silently drop (send the email without the
    'cc finance' the user asked for). Treat it as a decline carrying that feedback
    so the agent re-proposes with the change instead of running the wrong action."""
    if action == "approve" and (feedback or "").strip():
        return "deny", feedback
    return action, feedback


async def _safe_resolve(
    approval_id: str, user_id: str, decision: Literal["approve", "deny"], feedback: str | None
) -> None:
    """Apply one decision, tolerating an already-resolved/expired approval."""
    with contextlib.suppress(ApprovalRequestNotFoundError, ApprovalRequestForbiddenError):
        await resolve_approval(
            approval_id=approval_id,
            user_id=user_id,
            kind=decision,
            feedback=feedback,
            scope="once",
        )


def _history_block(history: list[MessageDict] | None) -> str:
    """Recent turns as ``role: content`` lines, per-turn and total bounded."""
    if not history:
        return ""
    lines = [
        f"{turn.get('role', '')}: {clip_text(turn.get('content') or '', HIL_CLASSIFIER_MAX_ARG_CHARS)}"
        for turn in history
    ]
    return clip_text("\n".join(lines), HIL_CLASSIFIER_MAX_DETAIL_CHARS)


def _prompt(message: str, action_details: list[str], history: list[MessageDict] | None) -> str:
    action = "\n\n".join(action_details)
    history_block = _history_block(history)
    context = (
        f"RECENT CONVERSATION (oldest to newest, context only):\n{history_block}\n\n"
        if history_block
        else ""
    )
    return (
        "The user has a pending action awaiting their approval. They did NOT click "
        "approve or decline — they replied in chat. Classify what the reply means.\n\n"
        f"PENDING ACTION (what the assistant is waiting to do):\n{action}\n\n"
        f"{context}"
        f"THE USER'S REPLY:\n{message!r}\n\n"
        "Classify the reply as exactly one of:\n"
        "- 'approve' — the user accepts the pending action EXACTLY as proposed, with "
        "no change (e.g. 'yes', 'go ahead', 'ok send it'). Leave `feedback` empty.\n"
        "- 'deny' — the user does NOT want the action run as proposed. This INCLUDES a "
        "plain refusal ('no', 'don't'), a redirect or correction ('no, send it to Bob "
        "instead', 'actually make it tomorrow'), AND an acceptance that attaches ANY "
        "change, addition, or condition to it ('yes but cc finance', 'ok, but shorten "
        "it first'). The assistant cannot edit the action's arguments, so any requested "
        "change means the current action is wrong: mark it 'deny' and put the change "
        "verbatim in `feedback`.\n"
        "- 'unrelated' — a brand-new, standalone request that does NOT object to the "
        "pending action and does not reference it (e.g. the pending action is 'send "
        "email' and the user asks 'what's on my calendar tomorrow?').\n\n"
        "Rules:\n"
        "- An unambiguous 'yes'/'no' is decisive on its own. Honor it directly. The "
        "recent conversation and action details are background for interpreting an "
        "ambiguous reply — never grounds to overturn a clear yes or no.\n"
        "- Only 'approve' when the action should run UNCHANGED. If the reply adds, "
        "changes, or conditions anything about it, that is 'deny' with the change in "
        "`feedback` — never approve an action the user wants changed.\n"
        "- If the reply objects to, corrects, or countermands the pending action, it "
        "is 'deny' (with the correction in `feedback`) even when it also proposes a "
        "different action. 'unrelated' is only for a reply that adds a new topic "
        "WITHOUT objecting to the pending action.\n"
        "- If unsure whether the reply bears on the pending action and it expresses "
        "any objection, choose 'deny'."
    )


def _batch_prompt(
    message: str, action_details: list[str], history: list[MessageDict] | None
) -> str:
    actions = "\n\n".join(
        f"{index}. {detail}" for index, detail in enumerate(action_details, start=1)
    )
    history_block = _history_block(history)
    context = (
        f"RECENT CONVERSATION (oldest to newest, context only):\n{history_block}\n\n"
        if history_block
        else ""
    )
    return (
        "The assistant is waiting for the user to approve or decline these "
        "numbered pending actions:\n"
        f"{actions}\n\n"
        f"{context}"
        f"THE USER'S REPLY:\n{message!r}\n\n"
        "Decide per action. A blanket answer applies to all of them: a plain "
        "'yes'/'go ahead' approves every action, a plain 'no'/'don't' declines "
        "every action. A selective answer names some actions — mark each named one "
        "approve or deny. Decide the UNNAMED actions by whether the reply is "
        "exclusive: an exclusive answer ('just the email', 'only the email', 'just "
        "do that and nothing else', 'skip the rest') means the user wants ONLY the "
        "named actions — mark every unnamed action 'deny'. A non-exclusive partial "
        "answer ('approve the email', 'yes to the first one') decides only what it "
        "names and leaves each unnamed action 'leave' (the user may still answer the "
        "rest separately). Also mark an action 'deny' when the reply rejects, "
        "corrects, redirects, or attaches any change/condition to THAT action (put "
        "the correction in its `feedback`) — the assistant cannot edit an action's "
        "arguments, so 'do it but change X' is 'deny' with X in `feedback`, never "
        "'approve'. "
        "If the message asks a question about the actions or is otherwise not a "
        "decision on any of them, mark all 'leave'. Set unrelated=true ONLY when the "
        "message is clearly a new, different request that ignores the pending actions "
        "without objecting to them. An unambiguous 'yes'/'no' is decisive on its own; "
        "the recent conversation is background for ambiguous replies, never grounds to "
        "overturn a clear answer. Extract any feedback or conditions per action."
    )
