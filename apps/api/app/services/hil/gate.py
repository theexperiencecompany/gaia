"""HIL approval gate: pause destructive tool calls until the user decides.

One canonical ``gate_tool_call`` wraps every tool execution. It is used by both
of DynamicToolNode's execution paths (the middleware chain and the parent
ToolNode) via thin adapters — the middleware class in
``app/agents/middleware/hil_approval.py`` and the composed ToolNode wrapper in
``dynamic_tool_node.py``. Living in the service layer keeps it importable from
the override package without a middleware↔override cycle.

The pause is LangGraph's native ``interrupt()``: the run checkpoints to Postgres
and exits, so an approval survives a restart/deploy. It resumes when
``resolve_approval`` re-dispatches the thread with ``Command(resume=...)``.

Two invariants hold this together:

* ``interrupt()`` raises ``GraphInterrupt``. It is control flow, never an error —
  it must never be caught here (or by the wrappers above; see the
  ``GraphBubbleUp`` guards in ``executor.py`` / ``dynamic_tool_node.py``).
* On resume the node re-runs from the top, so every statement *before*
  ``interrupt()`` executes twice. All of it must be idempotent, and the real tool
  must only ever run *after* the decision comes back.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command, interrupt

from app.agents.tools.core.registry import get_tool_registry
from app.constants.hil import HIL_EXEMPT_TOOLS
from app.constants.log_tags import LogTag
from app.models.hil_models import HIL_DEFAULT_MODE, HILPreferences
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
from app.services.hil.classification import is_tool_destructive, mcp_destructive_hint
from app.services.hil.intent import IntentDecision, judge_intent, prior_tool_calls
from app.services.hil.preferences import get_hil_preferences, set_tool_override
from shared.py.wide_events import log

Handler = Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]

# The gate's decision for one destructive-eligible call:
#   allow — run without asking; ask — pause for approval; auto — let the intent
#   judge decide between the two.
GatingPolicy = Literal["allow", "ask", "auto"]

_DENIED_TEMPLATE = (
    "The user declined to run `{tool}`. The action was NOT performed.{feedback} "
    "Adjust your approach based on this, or ask the user what they'd like "
    "instead. Do not retry the same call unchanged."
)
_TIMEOUT_TEMPLATE = (
    "The approval request for `{tool}` expired without a response. The action "
    "was NOT performed. Tell the user you were waiting for their approval and "
    "that they can ask again when ready."
)
# An approval gate that cannot determine whether a call is safe must not run it —
# but the refusal must read as a system failure, never as a decision the user made.
_GATE_ERROR_TEMPLATE = (
    "The approval system could not verify `{tool}` due to an internal error. The "
    "action was NOT performed and the user was NOT asked. Tell the user a system "
    "error prevented the action and they can retry."
)

# The only statuses a resume payload may carry; anything else is treated as a
# denial ("abandoned" resumes as a deny — resolution.py maps it before sending).
_RESUMABLE_STATUSES: frozenset[str] = frozenset({"approved", "denied", "timeout"})


@dataclass
class _GateContext:
    """The interactive-run identity needed to ask a live user for approval."""

    stream_id: str
    user_id: str
    conversation_id: str
    # The user's own recent turns, oldest first, the live request last. May be empty on
    # entry paths with no user message; the intent judge treats that as unverifiable.
    user_messages: list[str]


async def gate_tool_call(request: ToolCallRequest, handler: Handler) -> ToolMessage | Command[Any]:
    """Run ``handler`` unless HIL must first get the user's approval."""
    tool_name, tool_call_id, args = _unpack_tool_call(request)
    if tool_name in HIL_EXEMPT_TOOLS:
        return await handler(request)

    context = _read_gate_context(request)
    if context is None:
        return await handler(request)

    # Scoped to the gate's own decision I/O — never wraps ``handler``, so a tool's
    # own failure still surfaces as a tool error rather than a spurious denial.
    try:
        policy = await _gating_policy(request, context, tool_name)
    except GraphBubbleUp:
        raise
    except Exception as e:  # noqa: BLE001 — an approval gate must fail closed
        log.error(f"{LogTag.HIL} Gate check failed for {tool_name}; denying: {e}")
        return _gate_error_message(tool_name, tool_call_id)

    if policy == "allow":
        return await handler(request)
    return await _ask_or_auto_run(request, handler, context, policy, tool_name, tool_call_id, args)


async def _gating_policy(
    request: ToolCallRequest, context: _GateContext, tool_name: str
) -> GatingPolicy:
    """Resolve mode + the gated tool set into one decision.

    The gated set is the same in both gating modes: a tool is gated when the user's
    per-tool override says so, else when it classifies as destructive. ``mode`` only
    decides what happens to that set — ask the user, or let the intent judge decide.
    """
    try:
        prefs = await get_hil_preferences(context.user_id)
    except Exception:
        if HIL_DEFAULT_MODE != "always_allow":
            raise  # a gating default → the outer guard fails closed
        # HIL is opt-in and unlaunched: a Redis/Mongo blip here must not gate
        # every tool call for the overwhelmingly common HIL-off user. Loud log,
        # then behave as the default mode.
        log.error(f"{LogTag.HIL} Preferences unavailable; treating HIL as {HIL_DEFAULT_MODE}")
        return "allow"

    if prefs.mode == "always_allow":
        return "allow"
    if not await _is_gated(prefs, tool_name, getattr(request, "tool", None)):
        return "allow"
    return "auto" if prefs.mode == "auto" else "ask"


async def _is_gated(prefs: HILPreferences, tool_name: str, tool: BaseTool | None) -> bool:
    """Whether this tool needs approval — the set both gating modes act on.

    A user's explicit per-tool choice wins over the classifier in both directions — even
    over an MCP destructiveHint — since it's a deliberate account setting.
    """
    override = prefs.tool_overrides.get(tool_name)
    if override is not None:
        return override
    return await is_tool_destructive(
        tool_name,
        getattr(tool, "description", "") or "",
        destructive_hint=mcp_destructive_hint(tool),
    )


async def _other_gated_call_in_turn(
    request: ToolCallRequest, user_id: str, tool_call_id: str
) -> bool:
    """Whether the model asked for another gated tool in this same AI message.

    If it did, this call must not auto-run: the sibling will ``interrupt()``, and
    LangGraph re-runs the *whole node* on resume, so a handler that ran before the pause
    runs a second time (verified — a send became two sends). Auto-approval therefore
    applies only when it is the turn's only gated action; several destructive actions in
    one turn are confirmed together, which is also the behaviour worth having.

    A sibling whose tool object isn't to hand classifies from the registry alone and
    fails closed to gated, so an unknown sibling suppresses auto-approval rather than
    risking the double-run.
    """
    prefs = await get_hil_preferences(user_id)
    for call in _current_tool_calls(request.state):
        if call.get("id") == tool_call_id:
            continue
        name = call.get("name", "")
        if name and name not in HIL_EXEMPT_TOOLS and await _is_gated(prefs, name, None):
            return True
    return False


def _current_tool_calls(state: Any) -> list[dict[str, Any]]:
    """The tool calls of the AI message this node is executing (its last one)."""
    messages = _state_get(state, "messages")
    for message in reversed(messages if isinstance(messages, list) else []):
        calls = getattr(message, "tool_calls", None)
        if calls:
            return list(calls)
    return []


def _state_get(state: Any, key: str) -> Any:
    if isinstance(state, dict):
        return state.get(key)
    getter = getattr(state, "get", None)
    return getter(key) if callable(getter) else getattr(state, key, None)


async def _ask_or_auto_run(
    request: ToolCallRequest,
    handler: Handler,
    context: _GateContext,
    policy: GatingPolicy,
    tool_name: str,
    tool_call_id: str,
    args: dict[str, Any],
) -> ToolMessage | Command[Any]:
    """Auto-judge (auto mode), then either run the tool or pause for approval."""
    approval_id = approval_id_for(context.conversation_id, tool_call_id)
    tool_call = {"id": tool_call_id, "name": tool_name, "args": args}
    decision: IntentDecision | None = None

    try:
        # The user already declined this exact call earlier in the turn. Re-asking
        # is the loop we want to kill (the executor doesn't learn the subagent was
        # declined, so it retries) — auto-deny with their original feedback instead.
        prior = await recall_declined_call(context.stream_id, tool_name, args)
        if prior is not None:
            log.info(f"{LogTag.HIL} auto-denying {tool_name}: declined earlier this turn")
            return _refusal_message(tool_name, tool_call_id, prior)

        integration_name = await _integration_name_for(tool_name)
        summary = build_summary(tool_name, args, integration_name)

        if policy == "auto":
            # Replay guard: this node re-runs top-to-bottom on every interrupt() resume,
            # and the judge is a non-deterministic LLM call. A pre-existing record means a
            # prior run already published a card — skip the judge and go straight to the
            # (idempotent) pause below, so the resume value lands on the interrupt() it
            # expects. Paired with the sibling check, an auto-approved call never replays.
            if await get_approval(approval_id) is None and not await _other_gated_call_in_turn(
                request, context.user_id, tool_call_id
            ):
                decision = await judge_intent(
                    user_messages=context.user_messages,
                    tool_name=tool_name,
                    description=getattr(getattr(request, "tool", None), "description", "") or "",
                    args=args,
                    summary=summary,
                    # Actions only — the agent's prose is never handed to its own gate.
                    prior_calls=prior_tool_calls(request.state, tool_call_id),
                )

        if decision is not None and decision.aligned:
            # A receipt, published before the handler runs: if the tool then fails, the
            # user still sees that GAIA decided to act and why.
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
        log.error(f"{LogTag.HIL} Could not publish approval for {tool_name}; denying: {e}")
        return _gate_error_message(tool_name, tool_call_id)

    # Run outside the fail-closed try so the tool's own failure surfaces as a tool
    # error, not a spurious gate denial (same reason the post-approval run below
    # sits outside it).
    if decision is not None and decision.aligned:
        log.info(f"{LogTag.HIL} auto-approved {tool_name}: {decision.reason}")
        return await handler(request)

    # The run checkpoints and exits here. Everything below executes only once a
    # decision resumes the thread — never in the same process invocation.
    outcome = _outcome_from_resume(
        interrupt(
            {
                "type": "hil_approval",
                "approval_id": approval_id,
                "tool_name": tool_name,
                "summary": summary,
                "integration_name": integration_name,
                "args_preview": args,
            }
        )
    )
    log.info(f"{LogTag.HIL} HIL decision for {tool_name}: {outcome.status}")
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
            await set_tool_override(context.user_id, tool_name, False)
        return await handler(request)

    # Remember an explicit decline so a retry of the same call this turn is
    # auto-denied without prompting again (timeouts aren't remembered — the user
    # may simply have been away).
    if outcome.status == "denied":
        await remember_declined_call(context.stream_id, tool_name, args, outcome.feedback)
    return _refusal_message(tool_name, tool_call_id, outcome)


def _outcome_from_resume(raw: Any) -> ApprovalOutcome:
    """Interpret the value handed back by ``Command(resume=...)``.

    ``resolution.py`` sends the already-resolved status; anything unrecognised is
    a denial — an approval must never be inferred from a malformed payload.
    """
    if not isinstance(raw, dict) or raw.get("status") not in _RESUMABLE_STATUSES:
        log.warning(f"{LogTag.HIL} Malformed HIL resume payload; denying")
        return ApprovalOutcome(status="denied", feedback=None)
    return ApprovalOutcome(
        status=raw["status"],
        feedback=raw.get("feedback"),
        scope=str(raw.get("scope", "once")),
    )


def _gate_error_message(tool_name: str, tool_call_id: str) -> ToolMessage:
    return ToolMessage(
        content=_GATE_ERROR_TEMPLATE.format(tool=tool_name),
        tool_call_id=tool_call_id,
        name=tool_name,
        additional_kwargs={"hil_status": "error"},
    )


def _read_gate_context(request: ToolCallRequest) -> _GateContext | None:
    """The run's approval identity, or ``None`` when it can't be gated.

    Only interactive runs qualify: a background workflow/queued run carries a
    stream_id but has no live client to approve, so gating it would just stall
    until timeout (background approvals are a later phase).
    """
    configurable = _configurable_of(request)
    stream_id = configurable.get("stream_id")
    user_id = configurable.get("user_id")
    # Never ``thread_id`` — inside the executor/subagent that is the
    # ``executor_<conv>`` wrapper, so the approval would be filed against a
    # conversation the client never asks about.
    conversation_id = configurable.get("conversation_id")
    if not stream_id or not user_id or not conversation_id:
        return None
    if configurable.get("execution_mode") == "background":
        return None
    # Inherited unchanged from comms (see build_agent_config) — inside the executor or
    # a subagent the local task is an agent-authored paraphrase, never the user's words.
    raw = configurable.get("user_messages")
    user_messages = [text for text in raw if isinstance(text, str)] if isinstance(raw, list) else []
    return _GateContext(stream_id, user_id, conversation_id, user_messages)


def _refusal_message(tool_name: str, tool_call_id: str, outcome: ApprovalOutcome) -> ToolMessage:
    """The synthetic ToolMessage that tells the model a denied/timed-out call
    did not run."""
    template = _TIMEOUT_TEMPLATE if outcome.status == "timeout" else _DENIED_TEMPLATE
    feedback = f" The user said: {outcome.feedback!r}." if outcome.feedback else ""
    return ToolMessage(
        content=template.format(tool=tool_name, feedback=feedback),
        tool_call_id=tool_call_id,
        name=tool_name,
        additional_kwargs={"hil_status": outcome.status},
    )


def _unpack_tool_call(request: ToolCallRequest) -> tuple[str, str, dict[str, Any]]:
    tool_call = request.tool_call
    if isinstance(tool_call, dict):
        return (
            tool_call.get("name", ""),
            tool_call.get("id", ""),
            tool_call.get("args", {}) or {},
        )
    return tool_call.name, tool_call.id, (tool_call.args or {})


def _configurable_of(request: ToolCallRequest) -> dict[str, Any]:
    runtime = getattr(request, "runtime", None)
    config = getattr(runtime, "config", {}) or {}
    if not isinstance(config, dict):
        return {}
    configurable = config.get("configurable", {})
    return configurable if isinstance(configurable, dict) else {}


async def _integration_name_for(tool_name: str) -> str | None:
    registry = await get_tool_registry()
    category = registry.get_category(registry.get_category_of_tool(tool_name))
    return category.integration_name if category else None
