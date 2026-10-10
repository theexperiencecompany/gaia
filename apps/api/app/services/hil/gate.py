"""The HIL approval gate: it decides whether a tool call may run, and never runs one.

One entry point, decide_tool_call — the only place a tool can run from. A call the
user has not answered pauses here; siblings are unaffected since each tool call is
its own node task (fanned via Send) and LangGraph persists completed tasks' writes
across an interrupt, as long as the checkpoint gets written (see subagent_runner's
drain note: durability="exit" breaking the stream early used to re-run siblings).

The gate orchestrates, not decides or renders: unpack (utils.py), resolve policy
(policy.py), judge intent (intent.py), publish card + record (bridge.py), speak to
the model (prompts.py). interrupt() raises GraphInterrupt as control flow, never
caught here nor by the wrappers above (the GraphBubbleUp guards in middleware/executor.py
and dynamic_tool_node.py). A decision is a record, not a resume payload, so one decision can
wake a run with several approvals outstanding; everything before a pause re-runs
on replay, re-reading the record instead of remembering.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import json
from typing import Any

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command, interrupt

from app.agents.tools.core.registry import get_tool_registry
from app.agents.tools.execute.dispatch import DispatchError, _validate_args
from app.constants.hil import (
    HIL_EXEMPT_TOOLS,
    HIL_STATUS_KWARG,
    SUBAGENT_RESUME_CONFIG_KEY,
    HILToolMessageStatus,
)
from app.constants.log_tags import LogTag
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.models.agent_models import AgentConfigurable, SubagentResumeItem
from app.models.hil_models import (
    ApprovalLedgerDocument,
    ApprovalProposal,
    HILApprovalRecord,
    HILApprovalStatus,
    LedgerState,
)
from app.services.feature_flags import is_hil_ledger_enabled, is_jev_judge_enabled
from app.services.hil.approvals_store import approval_id_for, get_approval
from app.services.hil.bridge import (
    ApprovalOutcome,
    GatedApproval,
    build_summary,
    publish_approval_request,
    publish_auto_approval,
    publish_decision,
    publish_ledger_request,
    recall_declined_call,
    remember_declined_call,
)
from app.services.hil.fingerprint import approval_fingerprint
from app.services.hil.intent import (
    AutoContext,
    AutoHistory,
    IntentDecision,
    JudgedCall,
    judge_intent,
    summarize_history,
)
from app.services.hil.jev_judge import JevIntentJudge
from app.services.hil.policy import (
    GatingPolicy,
    gated_tool_object,
    has_pausing_sibling,
    resolve_policy,
)
from app.services.hil.preferences import get_hil_preferences, set_tool_override
from app.services.hil.prompts import (
    AUTO_REJECT_TEMPLATE,
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
    recent_assistant_turns,
    tool_description,
    tool_schema,
    unpack_tool_call,
)
from app.utils.general_utils import clip_text
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
    # Background owner parked on any approval this run registers, for the resume
    # driver: ("workflow"|"todo", the workflow/todo id). Empty on live runs,
    # which resume through the executor inbox instead of re-enqueueing.
    owner_run_type: str = ""
    owner_id: str = ""
    # A background subagent's own run: its thread and the recipe that resumes it,
    # filed on every approval it raises so a decision can resume it from anywhere.
    subagent_thread_id: str | None = None
    subagent_resume: SubagentResumeItem | None = None


@dataclass(frozen=True)
class _Pending:
    """A call whose card is up and whose decision has not landed yet."""

    approval_id: str
    tool_name: str
    summary: str
    integration_name: str | None


async def decide_tool_call(request: ToolCallRequest) -> ToolMessage | None:
    """HIL's verdict for one call. None clears it to run.

    A ToolMessage IS the call's whole result — denied, timed out, or the gate itself
    failed, and nothing will execute. Pauses here when the user hasn't answered yet;
    the run checkpoints and EXITS on that interrupt(), and on resume the node
    replays from the top and this same call finds its decision on the record.
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
        return _tool_message(
            unpack_tool_call(request),
            f"{settled.tool_name} woke with no decision on its record "
            f"({settled.approval_id}) — a system error, not a denial. The action "
            "was NOT performed. Report the stall and continue without it.",
            "error",
        )
    return settled


async def _verdict(request: ToolCallRequest) -> ToolMessage | _Pending | None:
    """Where one call stands with HIL: cleared (None), blocked, or awaiting a user."""
    call = unpack_tool_call(request)
    if call.name in HIL_EXEMPT_TOOLS:
        return None

    context = read_gate_context(request)
    if context is None:
        # AUDIT HOLE (instrumented 2026-09-19): an identity-less call runs with no
        # gate, no record, no message, so its tool calls are invisible to HIL.
        # Keep until read_gate_context can fail closed without breaking system flows.
        log.warning(
            f"{LogTag.HIL} Gate skipped: no run identity on the call",
            tool_name=call.name,
        )
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
    if await is_hil_ledger_enabled(context.user_id):
        # Executor-free path: register PENDING and return. No interrupt, no
        # pause — background runs gate exactly like live ones, which is the
        # whole point (pausable is irrelevant when nobody needs to pause).
        return await _decide_ledger(request, context, call, policy)
    if not context.pausable:
        # The call is gated and HIL is on, but this run (background subagent, workflow,
        # scheduled task) has no live client to approve it. Fail closed: refuse rather
        # than run it unapproved or stall on an interrupt nothing can resume.
        log.info(f"{LogTag.HIL} Denying gated : run cannot pause for approval", name=call.name)
        return _unpausable_denial_message(call)
    return await _decide(request, context, policy, call)


async def _decide_ledger(
    request: ToolCallRequest,
    context: GateContext,
    call: GatedCall,
    policy: GatingPolicy,
) -> ToolMessage | None:
    """Ledger verdict: register PENDING and return, or clear an auto-aligned call.

    Executor-free path: dedup against live rows, surface reject memory, refuse
    same-run nag re-issues, else register and hand the model a pending id. Any
    failure fails closed (deny), never open. Returns None only for the
    auto-aligned case (the tool may run).
    """
    try:
        declined = await recall_declined_call(context.stream_id, call.name, call.args)
        if declined is not None:
            log.info(f"{LogTag.HIL} auto-denying : declined earlier this turn", name=call.name)
            return (
                _auto_reject_message(call, declined.feedback or "")
                if declined.auto
                else _refusal_message(call, declined)
            )
        auto = await _auto_ledger_verdict(request, context, call, policy)
        if auto.settled:
            return auto.message
        auto_note = auto.note
        invalid = await _invalid_args_message(request, context.user_id, call)
        if invalid is not None:
            return invalid
        fingerprint = approval_fingerprint(call.name, call.args)
        live = await approval_ledger_repository.find_live(fingerprint, context.conversation_id)
        if live is not None:
            return _live_envelope_message(call, context, live)
        denied = await approval_ledger_repository.find_latest_denied(
            fingerprint, context.conversation_id
        )
        if denied is not None and denied.proposing_run_id == context.stream_id:
            return _same_run_refusal_message(call, denied)
        deny_note = _prior_denial_note(denied)

        integration_name = await _integration_name_for(call.name)
        summary = build_summary(call.name, call.args, integration_name)
        # Owner is the worker thread, stable across runs: subagent threads read
        # "<integration>_<conversation>", the executor "executor_<...>", so a
        # later turn of the same worker can revoke what it proposed.
        configurable: AgentConfigurable = configurable_of(request)
        owner = configurable.get("thread_id") or "unknown"
        # blocked_by arrives with ordering chains (Phase 3): the chain joins the
        # fingerprint there, so identical calls on different chains never share
        # an envelope.
        ap_id = await approval_ledger_repository.register(
            ApprovalProposal(
                conversation_id=context.conversation_id,
                user_id=context.user_id,
                fingerprint=fingerprint,
                tool_name=call.name,
                args=call.args,
                summary=summary,
                preview=clip_text(json.dumps(call.args, default=str), 500),
                owner_agent=str(owner),
                proposing_run_id=context.stream_id,
                owner_run_type=context.owner_run_type,
                owner_id=context.owner_id,
            )
        )
        log.info(
            f"{LogTag.HIL} Ledger registered gated call",
            approval_id=ap_id,
            tool_name=call.name,
        )
        await publish_ledger_request(
            GatedApproval(
                approval_id=ap_id,
                stream_id=context.stream_id,
                user_id=context.user_id,
                conversation_id=context.conversation_id,
                tool_call=call,
                summary=summary,
                integration_name=integration_name,
            ),
            auto_reason=auto_note.strip() or None,
            owner_run_type=context.owner_run_type,
            owner_id=context.owner_id,
            # Live runs hold the card until the run ends (a mid-run revoke is
            # never shown); background runs have no watcher, so publish now.
            live=context.pausable,
        )
        # "allow" returned before this branch, so the only policies left are
        # the two that explain WHY this call is gated — the model deserves
        # that reason instead of a bare "do not retry".
        why = (
            "this tool needs the user's explicit approval"
            if policy == "ask"
            else "auto-approve did not cover this call, so it needs the user's decision"
        )
        return _tool_message(
            call,
            f"PENDING {ap_id}: {summary} queued — {why}. "
            f"{_pending_guidance(ap_id, background=not context.pausable)}"
            f"{deny_note}{auto_note}",
            "pending",
        )
    except GraphBubbleUp:
        raise
    except Exception as e:  # an approval gate must fail closed
        log.error(
            f"{LogTag.HIL} Ledger gate failed; denying",
            name=call.name,
            error=str(e),
            error_type=type(e).__name__,
        )
        return _gate_error_message(call)


def read_gate_context(request: ToolCallRequest) -> GateContext | None:
    """Return the run's approval identity, or None when the user cannot be identified.

    A background/queued run *is* returned (with pausable=False): it has no live client
    to approve, so the gate cannot ask — but a gated call there must be failed closed, not
    silently allowed, which is why it is no longer discarded here. Only a run missing an
    identity field is None, since without a user there is no policy to resolve.
    """
    configurable: AgentConfigurable = configurable_of(request)
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
    # Background owner for the resume driver: stamped on any approval this run
    # registers so the verdict can wake the right unit of work. Live runs leave
    # it empty — they resume through the executor inbox, never re-enqueueing.
    owner_run_type, owner_id = "", ""
    if not pausable:
        workflow_id = configurable.get("workflow_id") or ""
        todo_id = configurable.get("active_todo_id") or ""
        if workflow_id:
            owner_run_type, owner_id = "workflow", workflow_id
        elif todo_id:
            owner_run_type, owner_id = "todo", todo_id
    subagent_resume = configurable.get(SUBAGENT_RESUME_CONFIG_KEY)
    return GateContext(
        stream_id,
        user_id,
        conversation_id,
        turns,
        pausable,
        owner_run_type,
        owner_id,
        subagent_thread_id=configurable.get("thread_id") if subagent_resume else None,
        subagent_resume=subagent_resume,
    )


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
        # This call's OWN decision comes first: the record is keyed by tool_call_id,
        # unlike decline memory (keyed by name+args) — reading it second would let a
        # decline shadow the very decision the user just gave.
        record = await get_approval(approval_id)
        if record is not None and record.status.settled:
            return await _apply(record, context, call)

        # A RETRY of something the user already declined this turn. Re-asking is the loop
        # we want to kill (the executor never learns its subagent was declined, so it
        # retries) — auto-deny with their original feedback instead.
        declined = await recall_declined_call(context.stream_id, call.name, call.args)
        if declined is not None:
            log.info(f"{LogTag.HIL} auto-denying : declined earlier this turn", name=call.name)
            if declined.auto:
                return _auto_reject_message(call, declined.feedback or "")
            return _refusal_message(call, declined)

        invalid = await _invalid_args_message(request, context.user_id, call)
        if invalid is not None:
            return invalid

        integration_name = await _integration_name_for(call.name)
        summary = build_summary(call.name, call.args, integration_name)

        decision: IntentDecision | None = None
        if policy == "auto":
            decision = await _judge(request, context, call, record, summary)

        approval = GatedApproval(
            approval_id=approval_id,
            stream_id=context.stream_id,
            user_id=context.user_id,
            conversation_id=context.conversation_id,
            tool_call=call,
            summary=summary,
            integration_name=integration_name,
        )
        if decision is not None and decision.outcome == "accept":
            log.info(
                f"{LogTag.HIL} auto-approved",
                call_name=call.name,
                reason=decision.reason,
            )
            # The receipt says GAIA decided to act, and why. It is not a claim that the
            # action happened — the tool node runs it afterwards, like any other call.
            await publish_auto_approval(approval, reason=decision.reason)
            return None

        if decision is not None and decision.outcome == "reject":
            log.info(
                f"{LogTag.HIL} auto-rejected",
                call_name=call.name,
                reason=decision.reason,
            )
            return await _auto_reject(context, call, decision.reason)

        auto_reason = (
            f"Auto mode wasn't sure: {decision.reason}"
            if decision is not None and decision.outcome == "ask" and decision.reason
            else None
        )
        await publish_approval_request(
            approval,
            auto_reason=auto_reason,
            subagent_resume=context.subagent_resume,
            subagent_thread_id=context.subagent_thread_id,
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
    """Turn a settled record into the call's fate: None runs it, a message blocks it.

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

    None means "don't auto-approve, don't spend a judge call": either a record
    already exists (a card is up, the answer is the user's to give, and re-judging
    would re-run a non-deterministic LLM call on every replay), or a sibling call
    will pause, and the judge is the one thing in this node that isn't idempotent.
    """
    if record is not None:
        return None
    if await has_pausing_sibling(request, context.user_id, call.id):
        log.info(f"{LogTag.HIL} not auto-approving : a sibling call may pause", name=call.name)
        return None
    history = await _auto_history(context.user_id, call.name)
    never_auto = await _never_auto_tools(context.user_id)
    judge = None
    if await is_jev_judge_enabled(context.user_id):
        # JEV classifies first, LLM stays as its transport-failure fallback.
        judge = JevIntentJudge()
    tool = await gated_tool_object(request, context.user_id, call.name)
    return await judge_intent(
        AutoContext(
            user_id=context.user_id,
            history=history,
            never_auto_tools=never_auto,
        ),
        user_messages=context.user_messages,
        judge=judge,
        call=JudgedCall(
            tool_name=call.name,
            # The REAL tool's description — for an execute-proxied call the
            # request carries the proxy's object, which would mislead the judge.
            description=tool_description(tool),
            args=call.args,
            summary=summary,
            tool_schema=tool_schema(tool),
        ),
        # Prior actions and recent assistant words are provenance for arguments,
        # never authorization — only the user's turns authorize.
        prior_calls=prior_tool_calls(request.state, call.id),
        assistant_turns=recent_assistant_turns(request.state),
    )


async def _never_auto_tools(user_id: str) -> frozenset[str]:
    """Return the user's deny-rule set, or empty when prefs cannot be read.

    Empty-on-failure mirrors _auto_history: prefs were already read for policy
    resolution, so a blip here skips one refinement, never the call.
    """
    try:
        prefs = await get_hil_preferences(user_id)
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} never-auto list unreadable; judging without it",
            error=str(e),
            error_type=type(e).__name__,
        )
        return frozenset()
    return frozenset(prefs.never_auto_tools)


async def _auto_history(user_id: str, tool_name: str) -> AutoHistory:
    """Build the judge's memory, or blank when the store cannot produce it.

    A history failure must degrade to "no signal", never to an exception out
    of the gate (which fails closed into a deny) and never to authorization.
    """
    try:
        rows = await approval_ledger_repository.recent_tool_outcomes(user_id, tool_name)
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} auto history unavailable; judging without memory",
            tool_name=tool_name,
            error=str(e),
            error_type=type(e).__name__,
        )
        return AutoHistory()
    return summarize_history(rows)


def _outcome_from_record(record: HILApprovalRecord) -> ApprovalOutcome:
    """Return the decision as the record holds it — the one durable copy.

    AUTO_APPROVED reads as a plain approval: it means the user was not asked, not
    that anything happened. ABANDONED reads as a denial — the user moved on, so the
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


def _auto_reject_message(call: GatedCall, reason: str) -> ToolMessage:
    """Tell the model auto mode declined the call — refused, not asked."""
    return _tool_message(call, AUTO_REJECT_TEMPLATE.format(tool=call.name, reason=reason), "denied")


async def _auto_reject(context: GateContext, call: GatedCall, reason: str) -> ToolMessage:
    """Refuse with the reason and arm decline memory against a retry.

    The memory write is best-effort: losing it degrades to re-judging the
    retry, never to running it — the refusal itself is the decision.
    """
    try:
        await remember_declined_call(context.stream_id, call.name, call.args, reason, auto=True)
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} decline memory write failed; the retry will re-judge",
            tool_name=call.name,
            error=str(e),
            error_type=type(e).__name__,
        )
    return _auto_reject_message(call, reason)


def _refusal_message(call: GatedCall, outcome: ApprovalOutcome) -> ToolMessage:
    """Tell the model a denied or timed-out call did not run, and why."""
    timed_out = outcome.status is HILApprovalStatus.TIMEOUT
    template = TIMEOUT_TEMPLATE if timed_out else DENIED_TEMPLATE
    feedback = f" The user said: {outcome.feedback!r}." if outcome.feedback else ""
    status: HILToolMessageStatus = "timeout" if timed_out else "denied"
    # Each template uses only the fields it needs; format ignores the rest.
    content = template.format(tool=call.name, feedback=feedback, waited=approval_window_label())
    return _tool_message(call, content, status)


@dataclass(frozen=True)
class _AutoVerdict:
    """Auto mode's conclusion: either it settled the call, or it left a note for the ask."""

    settled: bool = False
    message: ToolMessage | None = None
    note: str = ""


async def _auto_ledger_verdict(
    request: ToolCallRequest, context: GateContext, call: GatedCall, policy: GatingPolicy
) -> _AutoVerdict:
    """Let auto mode settle a ledger-path call, or say why it still needs the user."""
    if policy != "auto":
        return _AutoVerdict()
    integration_name = await _integration_name_for(call.name)
    summary = build_summary(call.name, call.args, integration_name)
    decision = await _judge(request, context, call, None, summary)
    if decision is None:
        return _AutoVerdict()
    if decision.outcome == "accept":
        log.info(
            f"{LogTag.HIL} auto-approved (ledger path)",
            call_name=call.name,
            reason=decision.reason,
        )
        return _AutoVerdict(settled=True)
    if decision.outcome == "reject":
        log.info(
            f"{LogTag.HIL} auto-rejected (ledger path)",
            call_name=call.name,
            reason=decision.reason,
        )
        return _AutoVerdict(
            settled=True, message=await _auto_reject(context, call, decision.reason)
        )
    note = (
        f" Auto mode wasn't sure: {decision.reason}"
        if decision.outcome == "ask" and decision.reason
        else ""
    )
    return _AutoVerdict(note=note)


def _live_envelope_message(
    call: GatedCall, context: GateContext, live: ApprovalLedgerDocument
) -> ToolMessage:
    """Point the model at the live envelope this call collapsed into."""
    if live.state is LedgerState.APPROVED:
        return _tool_message(
            call,
            f"APPROVED {live.approval_id}: {live.summary} already approved, "
            "awaiting redeem — not awaiting the user's decision. Do not "
            "re-request it; redeem it or continue other work.",
            "pending",
        )
    return _tool_message(
        call,
        f"PENDING {live.approval_id}: {live.summary} already requested and "
        f"awaiting the user's decision. "
        f"{_pending_guidance(live.approval_id, background=not context.pausable)}",
        "pending",
    )


def _same_run_refusal_message(call: GatedCall, denied: ApprovalLedgerDocument) -> ToolMessage:
    """Refuse a re-issue of a call the user already denied inside this run."""
    denied_why = f" The user said: {denied.feedback!r}." if denied.feedback else ""
    return _tool_message(
        call,
        f"REFUSED {denied.approval_id}: the user denied {denied.summary} "
        f"in this run.{denied_why} "
        "DO NOT re-request it. State what you skipped and continue without it.",
        "denied",
    )


def _prior_denial_note(denied: ApprovalLedgerDocument | None) -> str:
    """Render the earlier-denial aside for a fresh pending message; empty when there is none."""
    if denied is None:
        return ""
    when = f" at {denied.decided_at.isoformat()}" if denied.decided_at else ""
    why = f", saying {denied.feedback!r}" if denied.feedback else ""
    return (
        f" The user denied this exact call{when}{why}. Only re-ask if "
        "something changed or the user asked for it."
    )


def _gate_error_message(call: GatedCall) -> ToolMessage:
    """Tell the model the gate itself failed — the user was never asked."""
    return _tool_message(call, GATE_ERROR_TEMPLATE.format(tool=call.name), "error")


def _unpausable_denial_message(call: GatedCall) -> ToolMessage:
    """Tell the model a gated call was refused because this run cannot ask for approval."""
    return _tool_message(call, UNPAUSABLE_DENIAL_TEMPLATE.format(tool=call.name), "denied")


async def _invalid_args_message(
    request: ToolCallRequest, user_id: str, call: GatedCall
) -> ToolMessage | None:
    """Fail fast on malformed args before any card exists.

    The user must never approve a call the model will have to retry: validate
    against the exact schema execution uses (dispatch._validate_args) and answer
    with the schema error instead of registering. Unresolvable and schemaless
    tools skip — execution validates authoritatively.
    """
    try:
        tool = await gated_tool_object(request, user_id, call.name)
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} Pre-validation tool resolve failed; skipping arg check",
            tool=call.name,
            error_type=type(e).__name__,
        )
        return None
    if tool is None:
        return None
    validated = _validate_args(tool, call.args)
    if isinstance(validated, DispatchError):
        return _tool_message(
            call,
            f"Invalid arguments for {call.name}: {validated.detail} "
            "Fix the arguments and retry — no approval was requested.",
            "error",
        )
    return None


def _pending_guidance(approval_id: str, *, background: bool = False) -> str:
    """Describe what the model can and cannot do about a pending card.

    Shared by the fresh-register and live-dedup branches so the two never
    drift: the card's lifecycle is identical whichever branch produced it.
    Background runs get the park wording: nobody is watching this stream, so
    the card lives in the Approvals tab and durable work resumes off it.
    """
    where = (
        "the Approvals tab (this run has no watcher; nothing here will wake it)"
        if background
        else "chat (web, mobile, desktop) when this run ends"
    )
    return (
        f"The approval card appears to the user in {where}, and they decide there; "
        "you cannot approve it yourself. "
        f'If this step is not needed, withdraw it with execute(tool_name="revoke", '
        f'data={{"id": "{approval_id}"}}) before the run ends and the user will never see it. '
        "If it is genuinely needed, leave it and move on to independent work "
        "or exit — you will be woken with the approval and run it via "
        'execute(tool_name="approve", data={"id": ...}). '
        "Re-calling with the same arguments returns the same pending id: it "
        "never runs the tool directly — after approval you run it once via "
        "the approve ticket."
    )


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
