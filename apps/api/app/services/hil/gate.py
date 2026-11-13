"""The HIL approval gate: it decides whether a tool call may run, and never runs one.

One entry point, decide_tool_call. A gated call is registered PENDING in the approval
ledger and the model gets the pending id back; nothing pauses. The decision arrives
later through ledger_decide, which wakes the agent with a ticket to redeem.

The gate orchestrates, not decides or renders: unpack (utils.py), resolve policy
(policy.py), judge intent (intent.py), register + publish the card (approval ledger,
bridge.py), speak to the model (prompts.py).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command

from app.agents.tools.core.registry import get_tool_registry
from app.agents.tools.execute.dispatch import _validate_args
from app.constants.hil import (
    AUTO_ASK_NOTE,
    HIL_EXEMPT_TOOLS,
    HIL_STATUS_KWARG,
    HILToolMessageStatus,
)
from app.constants.log_tags import LogTag
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.models.agent_models import AgentConfigurable
from app.models.execute_models import DispatchError
from app.models.hil_models import (
    ApprovalLedgerDocument,
    ApprovalProposal,
    LedgerState,
)
from app.services.analytics_service import capture
from app.services.feature_flags import is_jev_judge_enabled
from app.services.hil.bridge import GatedApproval, publish_ledger_request
from app.services.hil.describe import describe_call
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
    gated_tool_key,
    gated_tool_object,
    has_pausing_sibling,
    resolve_policy,
)
from app.services.hil.preferences import get_hil_preferences
from app.services.hil.prompts import GATE_ERROR_TEMPLATE
from app.services.hil.tool_key import hil_tool_key, mcp_tool_identity
from app.services.hil.utils import (
    GatedCall,
    configurable_of,
    prior_tool_calls,
    recent_assistant_turns,
    tool_description,
    tool_schema,
    unpack_tool_call,
)
from app.services.integrations.integration_resolver import IntegrationResolver
from app.utils.general_utils import clip_text
from shared.py.analytics import UserId
from shared.py.analytics.catalog.hil import HilDecisionSubmitted
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


async def decide_tool_call(request: ToolCallRequest) -> ToolMessage | None:
    """HIL's verdict for one call. None clears it to run.

    A ToolMessage IS the call's whole result: registered pending, refused, or the gate
    itself failed, and nothing executes now.
    """
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
    return await _decide_ledger(request, context, call, policy)


async def _decide_ledger(
    request: ToolCallRequest,
    context: GateContext,
    call: GatedCall,
    policy: GatingPolicy,
) -> ToolMessage | None:
    """Ledger verdict: register PENDING and return, or clear an auto-aligned call.

    Executor-free path: dedup against live rows, surface decline memory, refuse
    same-run nag re-issues, else register and hand the model a pending id. Any
    failure fails closed (deny), never open. Returns None only for the
    auto-aligned case (the tool may run).
    """
    try:
        auto = await _auto_ledger_verdict(request, context, call, policy)
        if auto.runs:
            return None
        auto_note = auto.note
        invalid = await _invalid_args_message(request, context.user_id, call)
        if invalid is not None:
            return invalid
        fingerprint = approval_fingerprint(call.name, call.args, call.account)
        live = await approval_ledger_repository.find_live(fingerprint, context.conversation_id)
        if live is not None:
            return _live_envelope_message(call, context, live)
        denied = await approval_ledger_repository.find_latest_denied(
            fingerprint, context.conversation_id
        )
        if denied is not None and denied.proposing_run_id == context.stream_id:
            return _same_run_refusal_message(call, denied)
        deny_note = _prior_denial_note(denied)

        integration_name = await _integration_name_for(request, context.user_id, call.name)
        description = describe_call(call.name, call.args, integration_name, call.account)
        summary = description.headline
        # Owner is the worker thread, stable across runs: subagent threads read
        # "<integration>_<conversation>", the executor "executor_<...>", so a
        # later turn of the same worker can revoke what it proposed.
        configurable: AgentConfigurable = configurable_of(request)
        owner = configurable.get("thread_id") or "unknown"
        # blocked_by arrives with ordering chains (Phase 3): the chain joins the
        # fingerprint there, so identical calls on different chains never share
        # an envelope.
        row = await approval_ledger_repository.register(
            ApprovalProposal(
                conversation_id=context.conversation_id,
                user_id=context.user_id,
                fingerprint=fingerprint,
                tool_name=call.name,
                tool_key=await gated_tool_key(request, context.user_id, call.name),
                args=call.args,
                account=call.account,
                summary=summary,
                preview=clip_text(json.dumps(call.args, default=str), 500),
                owner_agent=str(owner),
                proposing_run_id=context.stream_id,
                owner_run_type=context.owner_run_type,
                owner_id=context.owner_id,
            )
        )
        ap_id = row.approval_id
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
                description=description,
                integration_name=integration_name,
            ),
            asked_at=row.created_at,
            auto_reason=AUTO_ASK_NOTE if auto.asked else None,
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
    return GateContext(
        stream_id, user_id, conversation_id, turns, pausable, owner_run_type, owner_id
    )


async def _judge(
    request: ToolCallRequest,
    context: GateContext,
    call: GatedCall,
    summary: str,
) -> IntentDecision | None:
    """Ask the intent judge whether the user's request authorizes this call.

    None means "don't auto-approve, don't spend a judge call": a sibling call will
    pause, and the judge is the one thing in this node that isn't idempotent.
    """
    if await has_pausing_sibling(request, context.user_id, call.id):
        log.info(f"{LogTag.HIL} not auto-approving : a sibling call may pause", name=call.name)
        return None
    history = await _auto_history(context.user_id, call.name)
    tool = await gated_tool_object(request, context.user_id, call.name)
    never_auto = hil_tool_key(call.name, mcp_tool_identity(tool)) in await _never_auto_tools(
        context.user_id
    )
    judge = None
    if await is_jev_judge_enabled(context.user_id):
        # JEV classifies first, LLM stays as its transport-failure fallback.
        judge = JevIntentJudge()
    decision = await judge_intent(
        AutoContext(
            user_id=context.user_id,
            history=history,
            never_auto=never_auto,
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
    if decision.outcome == "accept":
        # An auto-run call has no card and no ledger row; this is its only record.
        capture(
            UserId(context.user_id),
            HilDecisionSubmitted(decision="approved", tool_name=call.name, via="auto"),
        )
    return decision


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


# --- what a blocked call tells the model (text lives in prompts.py) ---------------------


@dataclass(frozen=True)
class _AutoVerdict:
    """Auto mode's conclusion: run the call, or ask (asked) with a model-facing note."""

    runs: bool = False
    asked: bool = False
    note: str = ""


async def _auto_ledger_verdict(
    request: ToolCallRequest, context: GateContext, call: GatedCall, policy: GatingPolicy
) -> _AutoVerdict:
    """Let auto mode run a ledger-path call, or say why it still needs the user."""
    if policy != "auto":
        return _AutoVerdict()
    integration_name = await _integration_name_for(request, context.user_id, call.name)
    summary = describe_call(call.name, call.args, integration_name, call.account).headline
    decision = await _judge(request, context, call, summary)
    if decision is None:
        return _AutoVerdict()
    if decision.outcome == "accept":
        log.info(
            f"{LogTag.HIL} auto-approved (ledger path)",
            call_name=call.name,
            reason=decision.reason,
        )
        return _AutoVerdict(runs=True)
    note = f" Auto mode wasn't sure: {decision.reason}" if decision.reason else ""
    return _AutoVerdict(asked=True, note=note)


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


class ApprovalDestination(StrEnum):
    """Where a pending approval surfaces for the user, independent of its prose."""

    CHAT = "chat"
    CONVERSATION = "conversation"


_DESTINATION_WORDING: dict[ApprovalDestination, str] = {
    ApprovalDestination.CHAT: "their chat when this run ends",
    ApprovalDestination.CONVERSATION: (
        "this conversation, which shows in their chat list while it waits "
        "(this run has no watcher; nothing here will wake it)"
    ),
}


def _approval_destination(*, background: bool) -> ApprovalDestination:
    """Return the destination contract a pending approval is rendered from."""
    return ApprovalDestination.CONVERSATION if background else ApprovalDestination.CHAT


def _pending_guidance(approval_id: str, *, background: bool = False) -> str:
    """Describe what the model can and cannot do about a pending approval.

    Shared by the fresh-register and live-dedup branches so the two never
    drift: the approval's lifecycle is identical whichever branch produced it.
    Background runs get the park wording: nobody is watching this stream, so
    the approval waits in its conversation and durable work resumes off it.
    """
    where = _DESTINATION_WORDING[_approval_destination(background=background)]
    return (
        f"The approval request appears to the user in {where}, and they decide there; "
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


async def _integration_name_for(
    request: ToolCallRequest, user_id: str, tool_name: str
) -> str | None:
    """Name the approval card's integration: the registry category, else the MCP server."""
    registry = await get_tool_registry()
    category = registry.get_category(registry.get_category_of_tool(tool_name))
    if category is not None:
        return category.integration_name
    mcp_tool = mcp_tool_identity(await gated_tool_object(request, user_id, tool_name))
    if mcp_tool is None:
        return None
    resolved = await IntegrationResolver.resolve(mcp_tool.integration_id)
    return resolved.name if resolved else mcp_tool.integration_id
