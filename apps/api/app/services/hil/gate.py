"""The HIL approval gate: it decides whether a tool call may run, and never runs one.

One entry point, ``decide_tool_call``: the caller asks, and runs the tool only if the
answer is "yes". Every ``return await handler(request)`` this module used to contain is
gone, so there is exactly one place in the system a tool can run from.

A call the user has not answered pauses here. Its siblings are unaffected: each tool call
is its own node task (``create_agent`` fans them out with ``Send``), and LangGraph
persists the writes of the tasks that COMPLETED in an interrupting step, so they are not
re-run on resume. That only holds while the run's checkpoint actually gets written —
see the drain note in ``subagent_runner``, where breaking out of the stream early under
``durability="exit"`` used to throw it away and re-run the completed siblings.

The gate orchestrates; it does not decide or render. Each step is somebody else's job:

    unpack the call         utils.py       (what is being run, by whom)
    resolve the policy      policy.py      (allow / ask / auto)
    judge intent (auto)     intent.py      (does the user's request authorize it?)
    publish card + record   bridge.py      (what the user sees, what we keep)
    speak to the model      prompts.py     (what a blocked call is told)

Three invariants hold this together:

* ``interrupt()`` raises ``GraphInterrupt``. It is control flow, never an error — it must
  never be caught here, nor by the wrappers above (see the ``GraphBubbleUp`` guards in
  ``executor.py`` / ``dynamic_tool_node.py``).
* **A decision is a record**, never a resume payload. ``resolve_approval`` writes it to
  Mongo; the ``Command(resume=...)`` that follows is only a wake-up, and its value is
  deliberately ignored. That is what lets one decision wake a run with several approvals
  outstanding without anything being lost or double-applied.
* Everything before a pause runs again on the replay, so all of it is idempotent: every
  pass re-reads the record instead of remembering what it did last time.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command, interrupt

from app.agents.tools.core.registry import get_tool_registry
from app.constants.hil import (
    HIL_EXEMPT_TOOLS,
    HIL_STATUS_KWARG,
    HILToolMessageStatus,
)
from app.constants.log_tags import LogTag
from app.models.hil_models import HILApprovalRecord, HILApprovalStatus
from app.services.hil.approvals_store import approval_id_for, get_approval
from app.services.hil.bridge import (
    ApprovalOutcome,
    build_summary,
    publish_approval_request,
    publish_auto_approval,
    publish_decision,
    recall_declined_call,
    remember_declined_call,
)
from app.services.hil.intent import IntentDecision, JudgedCall, judge_intent
from app.services.hil.policy import GatingPolicy, has_pausing_sibling, resolve_policy
from app.services.hil.preferences import set_tool_override
from app.services.hil.prompts import (
    DENIED_TEMPLATE,
    GATE_ERROR_TEMPLATE,
    TIMEOUT_TEMPLATE,
    UNPAUSABLE_DENIAL_TEMPLATE,
)
from app.services.hil.utils import (
    GatedCall,
    approval_window_label,
    configurable_of,
    prior_tool_calls,
    tool_description,
    tool_of,
    unpack_tool_call,
)
from shared.py.wide_events import log

Handler = Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]


@dataclass(frozen=True)
class GateContext:
    """The run's identity — who to ask, what they asked for, and whether we can ask."""

    stream_id: str
    user_id: str
    conversation_id: str
    # The user's own recent turns, oldest first, the live request last. May be empty on
    # entry paths with no user message; the intent judge treats that as unverifiable.
    user_messages: list[str]
    # Whether this run can pause for approval. A background/queued run carries an identity
    # but has no live client to answer, so a gated call there is failed closed, not asked.
    pausable: bool


@dataclass(frozen=True)
class _Pending:
    """A call whose card is up and whose decision has not landed yet."""

    approval_id: str
    tool_name: str
    summary: str
    integration_name: str | None


async def decide_tool_call(request: ToolCallRequest) -> ToolMessage | None:
    """HIL's verdict for one call. ``None`` clears it to run.

    A ToolMessage IS the call's whole result — it was denied, timed out, or the gate
    itself failed, and nothing will execute. The gate decides and never executes: the
    caller runs the tool, so there is exactly one place a tool can run from.

    Pauses here when the user has not answered yet. The run checkpoints and EXITS on
    that ``interrupt()``; on resume the node replays from the top and this same call
    finds its decision on the record.
    """
    verdict = await _verdict(request)
    if not isinstance(verdict, _Pending):
        return verdict

    interrupt(
        {
            "type": "hil_approval",
            "approval_id": verdict.approval_id,
            "tool_name": verdict.tool_name,
            "summary": verdict.summary,
            "integration_name": verdict.integration_name,
        }
    )
    # Reached only on the replay, with the decision now durable on the record. Deciding
    # again (rather than trusting the resume value) is what lets ONE decision wake a run
    # holding several outstanding approvals without any of them being misapplied.
    settled = await _verdict(request)
    if isinstance(settled, _Pending):
        log.error(
            f"{LogTag.HIL} resumed with no decision on its record",
            approval_id=settled.approval_id,
            tool_name=settled.tool_name,
        )
        return _unpausable_denial_message(unpack_tool_call(request))
    return settled


async def _verdict(request: ToolCallRequest) -> ToolMessage | _Pending | None:
    """Where one call stands with HIL: cleared (``None``), blocked, or awaiting a user."""
    call = unpack_tool_call(request)
    if call.name in HIL_EXEMPT_TOOLS:
        return None

    context = read_gate_context(request)
    if context is None:
        return None

    try:
        policy = await resolve_policy(request, context.user_id, call.name)
    except GraphBubbleUp:
        raise
    except Exception as e:  # an approval gate must fail closed
        log.error(
            f"{LogTag.HIL} Gate check failed for ; denying",
            name=call.name,
            error=str(e),
            error_type=type(e).__name__,
        )
        return _gate_error_message(call)

    if policy == "allow":
        return None
    if not context.pausable:
        # The call is gated and HIL is on, but this run (background subagent, workflow,
        # scheduled task) has no live client to approve it. Fail closed: refuse rather
        # than run it unapproved or stall on an interrupt nothing can resume.
        log.info(f"{LogTag.HIL} Denying gated : run cannot pause for approval", name=call.name)
        return _unpausable_denial_message(call)
    return await _decide(request, context, policy, call)


def read_gate_context(request: ToolCallRequest) -> GateContext | None:
    """The run's approval identity, or ``None`` when the user cannot be identified.

    A background/queued run *is* returned (with ``pausable=False``): it has no live client
    to approve, so the gate cannot ask — but a gated call there must be failed closed, not
    silently allowed, which is why it is no longer discarded here. Only a run missing an
    identity field is ``None``, since without a user there is no policy to resolve.
    """
    configurable = configurable_of(request)
    stream_id = configurable.get("stream_id")
    user_id = configurable.get("user_id")
    # Never ``thread_id`` — inside the executor or a subagent that is the
    # ``executor_<conv>`` wrapper, so the approval would be filed against a conversation
    # the client never asks about.
    conversation_id = configurable.get("conversation_id")
    if not stream_id or not user_id or not conversation_id:
        return None
    pausable = configurable.get("execution_mode") != "background"
    # Inherited unchanged from comms (see build_agent_config): inside the executor or a
    # subagent the local task is an agent-authored paraphrase, never the user's words.
    raw = configurable.get("user_messages")
    turns = [text for text in raw if isinstance(text, str)] if isinstance(raw, list) else []
    return GateContext(stream_id, user_id, conversation_id, turns, pausable)


async def _decide(
    request: ToolCallRequest,
    context: GateContext,
    policy: GatingPolicy,
    call: GatedCall,
) -> ToolMessage | _Pending | None:
    """Surface the call and read where its decision stands.

    Idempotent by construction, because every pass re-reads the record rather than
    remembering anything: a replay re-publishes no card and re-runs no intent judge.
    """
    approval_id = approval_id_for(context.conversation_id, call.id)

    try:
        # This call's OWN decision comes first. The record is keyed by tool_call_id, so
        # it is specific to this call in a way the decline memory (keyed by name+args)
        # cannot be — and reading it second would let a decline shadow the very decision
        # the user just gave, leaving its card unsettled.
        record = await get_approval(approval_id)
        if record is not None and record.status.settled:
            return await _apply(record, context, call)

        # A RETRY of something the user already declined this turn. Re-asking is the loop
        # we want to kill (the executor never learns its subagent was declined, so it
        # retries) — auto-deny with their original feedback instead.
        declined = await recall_declined_call(context.stream_id, call.name, call.args)
        if declined is not None:
            log.info(f"{LogTag.HIL} auto-denying : declined earlier this turn", name=call.name)
            return _refusal_message(call, declined)

        integration_name = await _integration_name_for(call.name)
        summary = build_summary(call.name, call.args, integration_name)

        decision: IntentDecision | None = None
        if policy == "auto":
            decision = await _judge(request, context, call, record, summary)

        if decision is not None and decision.aligned:
            log.info(
                f"{LogTag.HIL} auto-approved",
                call_name=call.name,
                reason=decision.reason,
            )
            # The receipt says GAIA decided to act, and why. It is not a claim that the
            # action happened — the tool node runs it afterwards, like any other call.
            await publish_auto_approval(
                approval_id=approval_id,
                stream_id=context.stream_id,
                user_id=context.user_id,
                conversation_id=context.conversation_id,
                tool_call=call,
                summary=summary,
                integration_name=integration_name,
                reason=decision.reason,
            )
            return None

        await publish_approval_request(
            approval_id=approval_id,
            stream_id=context.stream_id,
            user_id=context.user_id,
            conversation_id=context.conversation_id,
            tool_call=call,
            summary=summary,
            integration_name=integration_name,
        )
        return _Pending(approval_id, call.name, summary, integration_name)
    except GraphBubbleUp:
        raise
    except Exception as e:  # an approval gate must fail closed
        log.error(
            f"{LogTag.HIL} Could not publish approval for ; denying",
            name=call.name,
            error=str(e),
            error_type=type(e).__name__,
        )
        return _gate_error_message(call)


async def _apply(
    record: HILApprovalRecord, context: GateContext, call: GatedCall
) -> ToolMessage | None:
    """Turn a settled record into the call's fate: ``None`` runs it, a message blocks it.

    The record is the decision — never the resume payload, which is only a wake-up.
    """
    outcome = _outcome_from_record(record)
    await publish_decision(
        record, outcome.status, stream_id=context.stream_id, feedback=outcome.feedback
    )
    if outcome.status == HILApprovalStatus.APPROVED:
        if outcome.scope == "always_tool":
            await set_tool_override(context.user_id, call.name, False)
        return None

    # Remember an explicit decline so a retry of the same call this turn is auto-denied
    # without prompting again. Timeouts are not remembered — the user may just be away.
    if outcome.status == HILApprovalStatus.DENIED:
        await remember_declined_call(context.stream_id, call.name, call.args, outcome.feedback)
    return _refusal_message(call, outcome)


async def _judge(
    request: ToolCallRequest,
    context: GateContext,
    call: GatedCall,
    record: HILApprovalRecord | None,
    summary: str,
) -> IntentDecision | None:
    """Ask the intent judge whether the user's request authorizes this call.

    ``None`` means "don't auto-approve, don't spend a judge call", for the two cases where
    auto-approval is off the table before the question is even worth asking:

    * **A record already exists** — a card is already up for this call, so the user has
      been asked and the answer is theirs to give. Re-judging would also re-run a
      non-deterministic LLM call on every replay of this node.
    * **A sibling call will pause** — this node will replay, and the judge is the one
      thing in it that is not idempotent; see ``policy.has_pausing_sibling``.
    """
    if record is not None:
        return None
    if await has_pausing_sibling(request, context.user_id, call.id):
        log.info(f"{LogTag.HIL} not auto-approving : a sibling call may pause", name=call.name)
        return None
    return await judge_intent(
        user_id=context.user_id,
        user_messages=context.user_messages,
        call=JudgedCall(
            tool_name=call.name,
            description=tool_description(tool_of(request)),
            args=call.args,
            summary=summary,
        ),
        # Actions only — the agent's own prose is never handed to its gate.
        prior_calls=prior_tool_calls(request.state, call.id),
    )


def _outcome_from_record(record: HILApprovalRecord) -> ApprovalOutcome:
    """The decision as the record holds it — the one durable copy.

    ``AUTO_APPROVED`` reads as a plain approval: it means the user was not asked, not
    that anything happened. ``ABANDONED`` reads as a denial — the user moved on, so the
    agent must not act.
    """
    if record.status is HILApprovalStatus.AUTO_APPROVED:
        status = HILApprovalStatus.APPROVED
    elif record.status is HILApprovalStatus.ABANDONED:
        status = HILApprovalStatus.DENIED
    else:
        status = record.status
    return ApprovalOutcome(status=status, feedback=record.feedback, scope=record.scope)


# --- what a blocked call tells the model (text lives in prompts.py) ---------------------


def _refusal_message(call: GatedCall, outcome: ApprovalOutcome) -> ToolMessage:
    """Tell the model a denied or timed-out call did not run, and why."""
    timed_out = outcome.status is HILApprovalStatus.TIMEOUT
    template = TIMEOUT_TEMPLATE if timed_out else DENIED_TEMPLATE
    feedback = f" The user said: {outcome.feedback!r}." if outcome.feedback else ""
    status: HILToolMessageStatus = "timeout" if timed_out else "denied"
    # Each template uses only the fields it needs; format ignores the rest.
    content = template.format(tool=call.name, feedback=feedback, waited=approval_window_label())
    return _tool_message(call, content, status)


def _gate_error_message(call: GatedCall) -> ToolMessage:
    """Tell the model the gate itself failed — the user was never asked."""
    return _tool_message(call, GATE_ERROR_TEMPLATE.format(tool=call.name), "error")


def _unpausable_denial_message(call: GatedCall) -> ToolMessage:
    """Tell the model a gated call was refused because this run cannot ask for approval."""
    return _tool_message(call, UNPAUSABLE_DENIAL_TEMPLATE.format(tool=call.name), "denied")


def _tool_message(call: GatedCall, content: str, status: HILToolMessageStatus) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=call.id,
        name=call.name,
        additional_kwargs={HIL_STATUS_KWARG: status},
    )


async def _integration_name_for(tool_name: str) -> str | None:
    registry = await get_tool_registry()
    category = registry.get_category(registry.get_category_of_tool(tool_name))
    return category.integration_name if category else None
