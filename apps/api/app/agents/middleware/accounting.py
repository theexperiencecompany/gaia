"""
LLM Call Accounting Middleware.

Emits a structured ``llm_call`` wide event after every model invocation with
input/cached/output tokens, credits charged, step index, and agent name. Also
emits ``recursion_high_water_mark`` when a run has consumed ≥80% of its
recursion limit so we can tune the cap from real data.

Also the budget enforcement seam: every model call records its USD cost into
the user's day/month budget windows and its tokens into the request tree's
aggregate counter (``app.services.cost_budget``), and ``awrap_model_call``
short-circuits the invocation with a user-facing stop message when the daily
cost budget or the per-request token ceiling is exhausted. This hook runs on
every execution path (chat, workflows, bots, voice, subagents), and the wall is
self-sufficient — when a path never stamped ``plan_type`` onto the configurable,
``get_budget_stop_reason`` derives it from the cached tier — so no entry point
can bypass the walls. The endpoint-level 429 gates are the nice UX, this is the
law.

Runs as a LangChain :class:`AgentMiddleware` via `create_agent(middleware=...)`.
"""

from collections.abc import Awaitable, Callable
import time
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime

from app.agents.llm.lane import ModelLane
from app.config.rate_limits import (
    PRIMARY_METERED_FEATURE,
    RateLimitPeriod,
    get_daily_cost_budget_usd,
    get_reset_time,
)
from app.constants.llm import (
    AGENT_RECURSION_LIMIT,
    LANE_FIELD_ID,
    RECURSION_HWM_FRACTION,
    UNKNOWN_MODEL_NAME,
)
from app.constants.log_tags import LogTag
from app.decorators.rate_limiting import build_rate_limit_card
from app.models.agent_models import agent_configurable, current_run_config
from app.models.payment_models import PlanType
from app.services.cost_budget import (
    BUDGET_WRAPUP_NOTICE,
    BudgetCheck,
    get_budget_stop_reason,
    is_budget_wrapup_threshold,
)
from app.services.llm_metering import (
    LLMCallContext,
    extract_finish_reason,
    extract_generation_id,
    extract_message_cost,
    extract_message_model,
    extract_message_provider,
    extract_message_usage,
    record_llm_call,
    resolve_channel,
)
from shared.py.wide_events import ModelContext, log


def _latest_ai_message(messages: list[AnyMessage]) -> AIMessage | None:
    for msg in reversed(messages or []):
        if isinstance(msg, AIMessage):
            return msg
    return None


class LLMAccountingMiddleware(AgentMiddleware[AgentState[Any], Any]):
    """Track LLM usage + emit wide events after every model call.

    Responsibilities:

    - ``@after_model``: read ``usage_metadata`` from the most recent AIMessage,
      compute USD credits via :func:`calculate_token_cost`, emit a
      ``llm_call`` wide event.
    - High-water-mark emission: when the run's step counter passes
      ``RECURSION_HWM_FRACTION * AGENT_RECURSION_LIMIT``, emit
      ``recursion_high_water_mark`` exactly once per thread.
    - ``@awrap_model_call``: the budget wall — short-circuits the model call
      with a stop message when the daily cost budget or per-request token
      ceiling is exhausted (see :func:`get_budget_stop_reason`); below that,
      injects a one-time-per-thread wrap-up notice once spend crosses
      ``BUDGET_WRAPUP_REMAINING_FRACTION``.
    """

    def __init__(self, agent_name: str, recursion_limit: int = AGENT_RECURSION_LIMIT) -> None:
        super().__init__()
        self.agent_name = agent_name
        self.recursion_limit = recursion_limit
        # Thread-local step counter, HWM-emitted flag, and before-model
        # monotonic timestamp. Keyed by thread_id so concurrent users don't
        # clobber each other.
        #
        # **Why in-memory (not Redis)?** A single run is bounded to ONE worker
        # — LangGraph drives all steps for a thread on the same process during
        # a run. The counters exist purely to drive per-run signals (step
        # index for the ``llm_call`` event, HWM "emit once per run" guard,
        # before/after timing delta). Crossing workers would over-emit HWM on
        # resume after a crash, and Redis round-trips would add non-trivial
        # overhead to every model step without improving correctness.
        self._step_counts: dict[str, int] = {}
        self._hwm_emitted: set[str] = set()
        self._budget_wrapup_emitted: set[str] = set()
        self._start_ts: dict[str, float] = {}
        # Wall time of the last provider call on each thread, measured around
        # the invocation itself in ``awrap_model_call``. ``_start_ts`` cannot
        # stand in: it spans before_model -> after_model, so it also carries
        # every other middleware in the stack. Consumed (popped) by the
        # ``aafter_model`` that meters that same call.
        self._invoke_ms: dict[str, float] = {}

    # --- helpers ---------------------------------------------------------

    def _thread_id(self, config: RunnableConfig) -> str:
        configurable = agent_configurable(config)
        return str(configurable.get("thread_id") or configurable.get("stream_id") or "unknown")

    def _next_step(self, thread_id: str) -> int:
        n = self._step_counts.get(thread_id, 0) + 1
        self._step_counts[thread_id] = n
        return n

    def _emit_budget_stop_card(self, stop_reason: str, plan_type: PlanType) -> None:
        """Stream a ``rate_limit_data`` frame so the frontend renders RateLimitCard
        instead of the bare stop text. Same helper ``with_rate_limiting`` uses in
        ``app.decorators.rate_limiting``; a missing stream writer (workflows, bots)
        is normal and logged at debug, never raised.
        """
        try:
            writer = get_stream_writer()
            writer(
                build_rate_limit_card(
                    feature=PRIMARY_METERED_FEATURE,
                    plan_required="pro" if plan_type == PlanType.FREE else None,
                    reset_time=get_reset_time(RateLimitPeriod.DAY).isoformat(),
                    current_plan=plan_type.value,
                    message=stop_reason,
                )
            )
        except Exception as e:
            log.debug(
                f"{LogTag.AGENT} Budget stop card not streamed",
                error=str(e),
                error_type=type(e).__name__,
            )

    # --- hooks -----------------------------------------------------------

    async def abefore_model(
        self,
        state: AgentState[Any],
        runtime: Runtime[Any],
    ) -> dict[str, Any] | None:
        """Pre-call hook: stamp the model-call start time for latency deltas.

        Budget GATING does not live here — a before_model return can only
        merge state; the custom graph loop (create_agent.acall_model) never
        routes on ``jump_to``, so it would not stop the call. Enforcement is
        in :meth:`awrap_model_call`, which can short-circuit the invocation.
        """
        del state, runtime  # state not consulted in this pre-call hook yet
        config = current_run_config()
        thread_id = self._thread_id(config)
        self._start_ts[thread_id] = time.monotonic()
        return None

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Budget wall: stop the run BEFORE the model is invoked when a limit binds.

        Runs on every model call in every execution path (chat, workflows,
        bots, voice, subagents) — the endpoint gates are UX; this is the
        backstop no entry point can route around. Checks, in order:

        1. Daily USD cost budget (free = usage wall, pro = abuse guard).
        2. Per-request aggregate token ceiling across the whole agent tree
           (keyed by the inherited ``root_request_id``).

        On a hit, returns the user-facing stop text as the final AIMessage —
        no tool calls, so the graph ends naturally. Fail-open on infra errors:
        a Redis hiccup must never take down the turn.

        Below the hard wall, when spend has crossed
        ``BUDGET_WRAPUP_REMAINING_FRACTION`` of the daily budget, injects a
        one-time-per-thread wrap-up notice (mirrors the recursion wrap-up in
        ``create_agent._maybe_inject_wrapup``) so the model lands the plane
        with what it has instead of dying mid-tool-call on the hard stop.
        """
        config = current_run_config()
        configurable = agent_configurable(config)
        user_id = configurable.get("user_id")
        root_request_id = configurable.get("root_request_id")
        # plan_type is passed through when the path stamped it (the hot chat path,
        # avoiding a Redis lookup); when it's absent or malformed we pass None and
        # get_budget_stop_reason derives the tier from the cached plan itself.
        plan_raw = configurable.get("plan_type")
        plan_type: PlanType | None
        try:
            plan_type = PlanType(plan_raw) if plan_raw else None
        except ValueError:
            plan_type = None

        try:
            check = await get_budget_stop_reason(
                str(user_id) if user_id else None,
                plan_type,
                str(root_request_id) if root_request_id else None,
            )
        except Exception as e:
            log.warning(
                f"{LogTag.AGENT} Budget check failed (failing open)",
                error=str(e),
                error_type=type(e).__name__,
            )
            check = BudgetCheck(None, None, None)

        if check.stop_reason is not None:
            log.warning(
                "budget_stop",
                event_name="budget_stop",
                agent_name=self.agent_name,
                user_id=user_id,
                plan_type=plan_raw,
                root_request_id=root_request_id,
            )
            # check.plan_type is always resolved alongside stop_reason (see
            # get_budget_stop_reason: every return that sets stop_reason also
            # sets plan_type), so the card always has a real plan to render.
            if check.plan_type is not None:
                self._emit_budget_stop_card(check.stop_reason, check.plan_type)
            return ModelResponse(result=[AIMessage(content=check.stop_reason)])

        thread_id = self._thread_id(config)
        if (
            check.spent_usd is not None
            and check.plan_type is not None
            and thread_id not in self._budget_wrapup_emitted
            and is_budget_wrapup_threshold(check.spent_usd, check.plan_type)
        ):
            self._budget_wrapup_emitted.add(thread_id)
            log.warning(
                "budget_wrapup_notice",
                event_name="budget_wrapup_notice",
                agent_name=self.agent_name,
                user_id=user_id,
                thread_id=thread_id,
                spent=check.spent_usd,
                budget=get_daily_cost_budget_usd(check.plan_type),
            )
            request = request.override(
                messages=[*request.messages, HumanMessage(content=BUDGET_WRAPUP_NOTICE)]
            )

        # The one seam that can see the provider call start and finish, so it
        # is the only place a real latency number exists. Measured across the
        # retry/fallback chain the handler owns, i.e. what the turn actually
        # waited for, and stashed for the ``aafter_model`` that meters it.
        invoke_start = time.monotonic()
        try:
            return await handler(request)
        finally:
            self._invoke_ms[thread_id] = round((time.monotonic() - invoke_start) * 1000, 2)

    async def aafter_model(
        self,
        state: AgentState[Any],
        runtime: Runtime[Any],
    ) -> dict[str, Any] | None:
        """Emit ``llm_call`` wide event after the model produces a response."""
        del runtime  # unused — config is fetched from the graph context var
        messages = (
            state.get("messages") if isinstance(state, dict) else getattr(state, "messages", [])
        )
        ai_msg = _latest_ai_message(messages or [])
        if ai_msg is None:
            return None

        config = current_run_config()
        configurable = agent_configurable(config)
        thread_id = self._thread_id(config)
        lane = ModelLane.from_configurable(configurable.get(LANE_FIELD_ID))
        model_name = (lane.model if lane else None) or UNKNOWN_MODEL_NAME
        provider = lane.provider if lane else UNKNOWN_MODEL_NAME
        if lane is None:
            # Priced as "unknown", which cannot match a real pricing entry, so the
            # call undercharges the budget. Loud rather than silent, matching
            # cost_budget's fail-open-but-visible convention — and reachable for a
            # deploy window by any bag written before lanes existed.
            log.warning(
                f"{LogTag.AGENT} No lane on the configurable — the call is priced as "
                "'unknown' and undercharges the budget (pre-lane queue item or HIL resume?)",
                agent_name=self.agent_name,
                thread_id=thread_id,
            )
        user_id = configurable.get("user_id")

        # Price the call (full input_tokens + cached_tokens, so the cached subset
        # is billed at the discounted rate rather than free) and record it into
        # the day/month budget windows plus the request tree's aggregate token
        # counter. This hook runs for every model call on every agent execution
        # path (chat, workflows, bots, voice, subagents) — all work the user
        # actively asked for, so it charges the budget. Auxiliary one-shot calls
        # reach the same helper via ``ainvoke_structured`` with
        # ``charge_to_budget=False`` (COGS observability only).
        usage = extract_message_usage(ai_msg)
        input_tokens = usage["input_tokens"]
        output_tokens = usage["output_tokens"]
        cached_tokens = usage["cached_tokens"]
        reasoning_tokens = usage["reasoning_tokens"]
        root_request_id = configurable.get("root_request_id")
        # The provider's own price when it reported one; the pricing table only
        # when it did not (direct Gemini, the sim lane).
        provider_cost = extract_message_cost(ai_msg)
        generation_id = extract_generation_id(ai_msg)
        workflow_id = configurable.get("workflow_id")
        total_cost = await record_llm_call(
            user_id=str(user_id) if user_id else None,
            model_name=str(model_name),
            usage=usage,
            root_request_id=str(root_request_id) if root_request_id else None,
            provider_cost=provider_cost,
            context=LLMCallContext(
                agent_name=self.agent_name,
                background=False,
                charge_to_budget=True,
                model_served=extract_message_model(ai_msg),
                provider=extract_message_provider(ai_msg),
                generation_id=generation_id,
                # The TRUE conversation id, which for a child agent is NOT the
                # checkpoint thread (that one is ``executor_<conv>``). Both are
                # passed so the ledger can carry each in its own field.
                conversation_id=(
                    str(configurable["conversation_id"])
                    if configurable.get("conversation_id")
                    else None
                ),
                thread_id=thread_id,
                workflow_id=str(workflow_id) if workflow_id else None,
                # The surface the turn came from — inherited by executor and
                # subagent runs, so a child call reports its root's channel.
                channel=resolve_channel(configurable),
                duration_ms=self._invoke_ms.pop(thread_id, None),
                finish_reason=extract_finish_reason(ai_msg),
            ),
        )

        step_index = self._next_step(thread_id)
        start = self._start_ts.pop(thread_id, None)
        handoff_latency_ms = (
            round((time.monotonic() - start) * 1000, 2) if start is not None else 0.0
        )
        # Aggregate per-step counts into the wide event so the end-of-stream
        # ``worker_task`` rollup reflects totals across the whole run, not just
        # the last step. ``log.set(model=...)`` does a shallow merge — without
        # reading the prior totals first, every step would overwrite the dict
        # and the final event would carry only the last step's numbers (which
        # is how ``cached_tokens`` / ``cache_hit_rate`` came back null).
        prior = log.get().get("model") or {}
        prior_input = int(prior.get("input_tokens") or 0)
        prior_output = int(prior.get("output_tokens") or 0)
        prior_cached = int(prior.get("cached_tokens") or 0)
        prior_reasoning = int(prior.get("reasoning_tokens") or 0)
        prior_cost = float(prior.get("cost_usd") or 0.0)

        agg_input = prior_input + input_tokens
        agg_output = prior_output + output_tokens
        agg_cached = prior_cached + cached_tokens
        agg_reasoning = prior_reasoning + reasoning_tokens
        agg_cost = prior_cost + total_cost
        agg_hit_rate = agg_cached / max(agg_input, 1) if agg_input else 0.0

        log.set(
            model=ModelContext(
                name=str(model_name),
                provider=str(provider),
                input_tokens=agg_input,
                output_tokens=agg_output,
                tokens_used=agg_input + agg_output,
                cached_tokens=agg_cached,
                reasoning_tokens=agg_reasoning,
                cache_hit_rate=round(agg_hit_rate, 4),
                cost_usd=round(agg_cost, 6),
                credits_charged=round(agg_cost, 6),
                step_index=step_index,
                agent_name=self.agent_name,
                handoff_latency_ms=handoff_latency_ms,
            )
        )
        log.info(
            "llm_call",
            llm_event="llm_call",
            agent_name=self.agent_name,
            model=model_name,
            thread_id=thread_id,
            user_id=user_id,
            input_tokens=input_tokens,
            cached_tokens=cached_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            cost_usd=total_cost,
            # Whether this figure is what the provider charged or what our price
            # table guessed — the two disagree by more than 10x per upstream, so
            # coverage of the reported price is worth being able to measure.
            cost_source="provider" if provider_cost is not None else "table",
            step_index=step_index,
            # Which UPSTREAM served this call. ``provider`` above is the lane's
            # configured provider (always "openrouter"), which cannot answer the
            # question a zero-cache call raises: did the request land on a
            # different upstream that holds no warm prefix, or did the prefix
            # break? This id resolves to the serving provider through
            # OpenRouter's generation-metadata endpoint, spending no model call.
            generation_id=generation_id,
        )

        # Recursion high-water-mark — emitted once per thread when the run
        # crosses the configured fraction of its recursion limit.
        hwm_cap = max(1, int(self.recursion_limit * RECURSION_HWM_FRACTION))
        if step_index >= hwm_cap and thread_id not in self._hwm_emitted:
            self._hwm_emitted.add(thread_id)
            log.warning(
                "recursion_high_water_mark",
                event_name="recursion_high_water_mark",
                agent_name=self.agent_name,
                thread_id=thread_id,
                user_id=user_id,
                step_index=step_index,
                recursion_limit=self.recursion_limit,
                hwm_cap=hwm_cap,
            )

        return None

    # Synchronous fallbacks (LangChain middleware dispatch to the sync path
    # when the graph is compiled without an async runtime).
    def before_model(self, state: AgentState[Any], runtime: Runtime[Any]) -> dict[str, Any] | None:
        del state, runtime
        thread_id = self._thread_id(current_run_config())
        self._start_ts[thread_id] = time.monotonic()
        return None

    def after_model(self, state: AgentState[Any], runtime: Runtime[Any]) -> dict[str, Any] | None:
        del state, runtime
        # Cost calc is async-only; in sync mode we still want the HWM signal.
        thread_id = self._thread_id(current_run_config())
        step_index = self._next_step(thread_id)
        hwm_cap = max(1, int(self.recursion_limit * RECURSION_HWM_FRACTION))
        if step_index >= hwm_cap and thread_id not in self._hwm_emitted:
            self._hwm_emitted.add(thread_id)
            log.warning(
                "recursion_high_water_mark (sync path)",
                event_name="recursion_high_water_mark",
                agent_name=self.agent_name,
                thread_id=thread_id,
                step_index=step_index,
                recursion_limit=self.recursion_limit,
                hwm_cap=hwm_cap,
            )
        return None
