"""The HIL approval gate: every tool call passes through here before it runs.

One canonical ``gate_tool_call`` wraps every tool execution. Both of DynamicToolNode's
execution paths use it via thin adapters — the middleware class in
``app/agents/middleware/hil_approval.py`` and the composed ToolNode wrapper in
``dynamic_tool_node.py``. Living in the service layer keeps it importable from the
override package without a middleware↔override cycle.

The gate orchestrates; it does not decide or render. Each step is somebody else's job:

    unpack the call         utils.py       (what is being run, by whom)
    resolve the policy      policy.py      (allow / ask / auto)
    judge intent (auto)     intent.py      (does the user's request authorize it?)
    publish card + record   bridge.py      (what the user sees, what we keep)
    speak to the model      prompts.py     (what a blocked call is told)

The pause is LangGraph's native ``interrupt()``: the run checkpoints to Postgres and
exits, so an approval survives a restart or deploy. ``resolve_approval`` re-dispatches
the thread with ``Command(resume=...)`` when the decision lands.

Two invariants hold this together:

* ``interrupt()`` raises ``GraphInterrupt``. It is control flow, never an error — it must
  never be caught here, nor by the wrappers above (see the ``GraphBubbleUp`` guards in
  ``executor.py`` / ``dynamic_tool_node.py``).
* On resume the node re-runs from the top, so every statement *before* ``interrupt()``
  executes twice. All of it must be idempotent, and the real tool must only ever run
  *after* the decision comes back.
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
    HIL_RESUMABLE_STATUSES,
    HIL_STATUS_KWARG,
    HILToolMessageStatus,
)
from app.constants.log_tags import LogTag
from app.models.hil_models import HILApprovalRecord
from app.services.hil.approvals_store import approval_id_for, get_approval
from app.services.hil.bridge import (
    ApprovalOutcome,
    build_summary,
    publish_approval_outcome,
    publish_approval_request,
    publish_auto_approval,
    recall_declined_call,
    remember_declined_call,
)
from app.services.hil.intent import IntentDecision, judge_intent
from app.services.hil.policy import GatingPolicy, has_pausing_sibling, resolve_policy
from app.services.hil.preferences import set_tool_override
from app.services.hil.prompts import (
    ALREADY_RAN_TEMPLATE,
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


async def gate_tool_call(request: ToolCallRequest, handler: Handler) -> ToolMessage | Command[Any]:
    """Run ``handler`` unless HIL must first get the user's approval."""
    call = unpack_tool_call(request)
    if call.name in HIL_EXEMPT_TOOLS:
        return await handler(request)

    context = read_gate_context(request)
    if context is None:
        return await handler(request)

    # Scoped to the gate's own decision I/O — never wraps ``handler``, so a tool's own
    # failure still surfaces as a tool error rather than a spurious denial.
    try:
        policy = await resolve_policy(request, context.user_id, call.name)
    except GraphBubbleUp:
        raise
    except Exception as e:  # noqa: BLE001 — an approval gate must fail closed
        log.error(f"{LogTag.HIL} Gate check failed for {call.name}; denying: {e}")
        return _gate_error_message(call)

    if policy == "allow":
        return await handler(request)
    if not context.pausable:
        # The call is gated and HIL is on, but this run (background subagent, workflow,
        # scheduled task) has no live client to approve it. Fail closed: refuse rather
        # than run it unapproved or stall on an interrupt nothing can resume.
        log.info(f"{LogTag.HIL} Denying gated {call.name}: run cannot pause for approval")
        return _unpausable_denial_message(call)
    return await _gate(request, handler, context, policy, call)


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


async def _gate(
    request: ToolCallRequest,
    handler: Handler,
    context: GateContext,
    policy: GatingPolicy,
    call: GatedCall,
) -> ToolMessage | Command[Any]:
    """Surface the call, then run it or pause for the user.

    Three outcomes: already declined this turn (refuse), auto-approved (receipt, then
    run), or paused (card, then ``interrupt()`` — resuming below only once decided).
    """
    approval_id = approval_id_for(context.conversation_id, call.id)
    tool_call = {"id": call.id, "name": call.name, "args": call.args}
    decision: IntentDecision | None = None

    try:
        # The user already declined this exact call this turn. Re-asking is the loop
        # we want to kill (the executor never learns its subagent was declined, so it
        # retries) — auto-deny with their original feedback instead.
        declined = await recall_declined_call(context.stream_id, call.name, call.args)
        if declined is not None:
            log.info(f"{LogTag.HIL} auto-denying {call.name}: declined earlier this turn")
            return _refusal_message(call, declined)

        # A replay of a call auto mode already RAN. It must neither run again (the action
        # is done, and these are irreversible by definition) nor fall through to the pause
        # below: it never reached ``interrupt()``, so pausing now would wait on an approval
        # that has no pending record and no card, and would swallow the resume value the
        # sibling's own ``interrupt()`` is expecting. ``has_pausing_sibling`` keeps auto
        # mode out of a replayable node in the first place; this is the backstop.
        record = await get_approval(approval_id)
        if record is not None and record.status == "auto_approved":
            log.info(f"{LogTag.HIL} {call.name} already ran under auto mode; not repeating")
            return _already_ran_message(call)

        integration_name = await _integration_name_for(call.name)
        summary = build_summary(call.name, call.args, integration_name)

        if policy == "auto":
            decision = await _judge(request, context, call, record, summary)

        if decision is not None and decision.aligned:
            # The receipt is published BEFORE the handler runs: if the tool then fails,
            # the user still sees that GAIA decided to act, and why.
            await publish_auto_approval(
                approval_id=approval_id,
                stream_id=context.stream_id,
                user_id=context.user_id,
                conversation_id=context.conversation_id,
                tool_call=tool_call,
                summary=summary,
                integration_name=integration_name,
                reason=decision.reason,
            )
        else:
            # Idempotent: a resume replay re-enters here, finds the record already
            # present, and re-publishes nothing.
            await publish_approval_request(
                approval_id=approval_id,
                stream_id=context.stream_id,
                user_id=context.user_id,
                conversation_id=context.conversation_id,
                tool_call=tool_call,
                summary=summary,
                integration_name=integration_name,
            )
    except GraphBubbleUp:
        raise
    except Exception as e:  # noqa: BLE001 — an approval gate must fail closed
        log.error(f"{LogTag.HIL} Could not publish approval for {call.name}; denying: {e}")
        return _gate_error_message(call)

    # Outside the fail-closed try, so a tool's own failure surfaces as a tool error
    # rather than a spurious gate denial.
    if decision is not None and decision.aligned:
        log.info(f"{LogTag.HIL} auto-approved {call.name}: {decision.reason}")
        return await handler(request)

    # The run checkpoints and EXITS here. Everything below executes only once a decision
    # resumes the thread — never in this process invocation.
    outcome = _outcome_from_resume(
        interrupt(
            {
                "type": "hil_approval",
                "approval_id": approval_id,
                "tool_name": call.name,
                "summary": summary,
                "integration_name": integration_name,
                "args_preview": call.args,
            }
        )
    )
    log.info(f"{LogTag.HIL} HIL decision for {call.name}: {outcome.status}")
    await publish_approval_outcome(
        stream_id=context.stream_id,
        approval_id=approval_id,
        tool_call=tool_call,
        summary=summary,
        integration_name=integration_name,
        outcome=outcome,
    )

    if outcome.status == "approved":
        if outcome.scope == "always_tool":
            await set_tool_override(context.user_id, call.name, False)
        return await handler(request)

    # Remember an explicit decline so a retry of the same call this turn is auto-denied
    # without prompting again. Timeouts are not remembered — the user may just be away.
    if outcome.status == "denied":
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

    * **A record already exists** — a prior run published a card for this call, so this is
      a resume replay (the node re-runs from the top, and the judge is a non-deterministic
      LLM call). Fall through to the pause, so the resume value lands on the ``interrupt()``
      that is expecting it. (An ``auto_approved`` record never gets here — the caller
      short-circuits it, since that call already ran and never paused.)
    * **A sibling call will pause** — running now would double-execute on resume; see
      ``policy.has_pausing_sibling``.
    """
    if record is not None:
        return None
    if await has_pausing_sibling(request, context.user_id, call.id):
        log.info(f"{LogTag.HIL} not auto-approving {call.name}: a sibling call may pause")
        return None
    return await judge_intent(
        user_messages=context.user_messages,
        tool_name=call.name,
        description=tool_description(tool_of(request)),
        args=call.args,
        summary=summary,
        # Actions only — the agent's own prose is never handed to its gate.
        prior_calls=prior_tool_calls(request.state, call.id),
    )


def _outcome_from_resume(raw: Any) -> ApprovalOutcome:
    """Interpret the value handed back by ``Command(resume=...)``.

    ``resolution.py`` sends the already-resolved status; anything unrecognised is a denial
    — an approval must never be inferred from a malformed payload.
    """
    if not isinstance(raw, dict) or raw.get("status") not in HIL_RESUMABLE_STATUSES:
        log.warning(f"{LogTag.HIL} Malformed HIL resume payload; denying")
        return ApprovalOutcome(status="denied", feedback=None)
    return ApprovalOutcome(
        status=raw["status"],
        feedback=raw.get("feedback"),
        scope=str(raw.get("scope", "once")),
    )


# --- what a blocked call tells the model (text lives in prompts.py) ---------------------


def _refusal_message(call: GatedCall, outcome: ApprovalOutcome) -> ToolMessage:
    """Tell the model a denied or timed-out call did not run, and why."""
    template = TIMEOUT_TEMPLATE if outcome.status == "timeout" else DENIED_TEMPLATE
    feedback = f" The user said: {outcome.feedback!r}." if outcome.feedback else ""
    status: HILToolMessageStatus = "timeout" if outcome.status == "timeout" else "denied"
    # Each template uses only the fields it needs; format ignores the rest.
    content = template.format(tool=call.name, feedback=feedback, waited=approval_window_label())
    return _tool_message(call, content, status)


def _gate_error_message(call: GatedCall) -> ToolMessage:
    """Tell the model the gate itself failed — the user was never asked."""
    return _tool_message(call, GATE_ERROR_TEMPLATE.format(tool=call.name), "error")


def _unpausable_denial_message(call: GatedCall) -> ToolMessage:
    """Tell the model a gated call was refused because this run cannot ask for approval."""
    return _tool_message(call, UNPAUSABLE_DENIAL_TEMPLATE.format(tool=call.name), "denied")


def _already_ran_message(call: GatedCall) -> ToolMessage:
    """Tell the model a replayed call already ran, so it does not ask for it again."""
    return _tool_message(call, ALREADY_RAN_TEMPLATE.format(tool=call.name), "already_ran")


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
