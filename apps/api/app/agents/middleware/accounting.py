"""LLM Call Accounting Middleware.

Emits a structured llm_call wide event after every model invocation
(tokens, credits, step index, agent name), and recursion_high_water_mark
at ≥80% of the recursion limit. Also the budget enforcement seam: every
call records USD cost into the user's day/month budget windows, and
awrap_model_call short-circuits with a stop message when the daily budget
or per-request token ceiling is exhausted — self-sufficient on every path
(chat, workflows, bots, voice, subagents) since get_budget_stop_reason
derives plan_type from the cached tier if a path never stamped it.

Runs as a LangChain :class:AgentMiddleware via create_agent(middleware=...).
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
from app.services.latency_metrics import observe_llm_call
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

    after_model computes USD credits and emits llm_call; high-water-mark
    fires recursion_high_water_mark once per thread past
    RECURSION_HWM_FRACTION; awrap_model_call is the budget wall, short-
    circuiting the call when budget/token ceilings are exhausted (see
    :func:get_budget_stop_reason) and injecting a wrap-up notice near the limit.
    """

    def __init__(self, agent_name: str, recursion_limit: int = AGENT_RECURSION_LIMIT) -> None:
        super().__init__()
        self.agent_name = agent_name
        self.recursion_limit = recursion_limit
        # Thread-local, keyed by thread_id. In-memory not Redis: a single run
        # is bounded to ONE worker, and Redis round-trips would add overhead
        # to every model step without improving correctness.
        self._step_counts: dict[str, int] = {}
        self._hwm_emitted: set[str] = set()
        self._budget_wrapup_emitted: set[str] = set()
        # Stacks, not scalars: two model calls can overlap on one thread (a
        # sync hook writing while an async run is in flight), and a scalar
        # lets the later stamp clobber the earlier one. LIFO matches nesting.
        self._start_ts: dict[str, list[float]] = {}
        # Wall time of each provider call, measured in ``awrap_model_call``
        # (``_start_ts`` spans before/after_model, carrying other middleware
        # too). Consumed (popped) by the ``aafter_model`` that meters it.
        self._invoke_ms: dict[str, list[float]] = {}

    # --- helpers ---------------------------------------------------------

    def _thread_id(self, config: RunnableConfig) -> str:
        configurable = agent_configurable(config)
        return str(configurable.get("thread_id") or configurable.get("stream_id") or "unknown")

    def _next_step(self, thread_id: str) -> int:
        n = self._step_counts.get(thread_id, 0) + 1
        self._step_counts[thread_id] = n
        return n

    @staticmethod
    def _pop_stamp(stamps: dict[str, list[float]], thread_id: str) -> float | None:
        """Pop this thread's newest stamp, dropping the key once the stack empties.

        These dicts live on a process-lifetime middleware instance keyed by
        thread, so a pop that leaves an empty list would grow one dead key per
        conversation forever.
        """
        stack = stamps.get(thread_id)
        if not stack:
            return None
        value = stack.pop()
        if not stack:
            del stamps[thread_id]
        return value

    def _emit_budget_stop_card(self, stop_reason: str, plan_type: PlanType) -> None:
        """Stream a rate_limit_data frame so the frontend renders RateLimitCard instead of bare text.

        Same helper with_rate_limiting uses; a missing stream writer
        (workflows, bots) is normal and logged at debug, never raised.
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
        routes on jump_to, so it would not stop the call. Enforcement is
        in :meth:awrap_model_call, which can short-circuit the invocation.
        """
        del state, runtime  # state not consulted in this pre-call hook yet
        config = current_run_config()
        thread_id = self._thread_id(config)
        self._start_ts.setdefault(thread_id, []).append(time.monotonic())
        return None

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Budget wall: stop the run BEFORE the model is invoked when a limit binds.

        Checks daily USD cost budget then per-request token ceiling; on a
        hit, returns the stop text as the final AIMessage. Fail-open on
        infra errors. Below the wall, injects a wrap-up notice near the limit.
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

        # The one seam that sees the provider call start and finish, across
        # the retry/fallback chain — stashed for the ``aafter_model`` that meters it.
        invoke_start = time.monotonic()
        try:
            response = await handler(request)
        except BaseException:
            # The graph aborts on a raised call, so the ``aafter_model`` that
            # would consume this call's stamps never runs. Drop them here or
            # the next call on this thread meters the failed one's timing.
            self._pop_stamp(self._start_ts, thread_id)
            raise
        self._invoke_ms.setdefault(thread_id, []).append(
            round((time.monotonic() - invoke_start) * 1000, 2)
        )
        return response

    async def aafter_model(
        self,
        state: AgentState[Any],
        runtime: Runtime[Any],
    ) -> dict[str, Any] | None:
        """Emit llm_call wide event after the model produces a response."""
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
            # Priced as "unknown", which undercharges the budget — loud
            # rather than silent, matching cost_budget's fail-open convention.
            log.warning(
                f"{LogTag.AGENT} No lane on the configurable — the call is priced as "
                "'unknown' and undercharges the budget (pre-lane queue item or HIL resume?)",
                agent_name=self.agent_name,
                thread_id=thread_id,
            )
        user_id = configurable.get("user_id")

        # Price the call into the day/month budget windows plus the request
        # tree's aggregate counter. Auxiliary calls use
        # ``charge_to_budget=False`` (COGS observability only) instead.
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
        invoke_ms = self._pop_stamp(self._invoke_ms, thread_id)
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
                duration_ms=invoke_ms,
                finish_reason=extract_finish_reason(ai_msg),
            ),
        )
        if invoke_ms is not None:
            observe_llm_call(invoke_ms / 1000.0, model=str(model_name), agent=self.agent_name)

        step_index = self._next_step(thread_id)
        start = self._pop_stamp(self._start_ts, thread_id)
        handoff_latency_ms = (
            round((time.monotonic() - start) * 1000, 2) if start is not None else 0.0
        )
        # Aggregate per-step counts so the rollup reflects run totals.
        # ``log.set`` shallow-merges, so prior totals must be read first.
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
            # Which UPSTREAM served this call — resolved via OpenRouter's
            # generation-metadata endpoint, spending no model call.
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
        self._start_ts.setdefault(thread_id, []).append(time.monotonic())
        return None

    def after_model(self, state: AgentState[Any], runtime: Runtime[Any]) -> dict[str, Any] | None:
        del state, runtime
        # Cost calc is async-only; in sync mode we still want the HWM signal.
        # Pop the before_model stamp so a mixed sync/async thread never leaks it.
        thread_id = self._thread_id(current_run_config())
        self._pop_stamp(self._start_ts, thread_id)
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
