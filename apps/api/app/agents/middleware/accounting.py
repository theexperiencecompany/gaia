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
from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_config
from langgraph.runtime import Runtime

from app.agents.llm.lane import ModelLane
from app.constants.llm import AGENT_RECURSION_LIMIT, LANE_FIELD_ID, RECURSION_HWM_FRACTION
from app.constants.log_tags import LogTag
from app.models.agent_models import agent_configurable
from app.models.payment_models import PlanType
from app.services.cost_budget import get_budget_stop_reason
from app.services.llm_metering import record_llm_call
from shared.py.wide_events import ModelContext, log


def _current_config() -> RunnableConfig:
    """Return the active ``RunnableConfig`` for the current graph run.

    LangChain's middleware hook signature is ``(state, runtime)`` — it does
    not hand the config in as a parameter. ``get_config()`` reads the config
    from LangGraph's runnable context-var (the same mechanism nodes use).
    Returns an empty dict when called outside a runnable context so this
    helper never raises on the sync fallback paths.
    """
    try:
        return get_config()
    except RuntimeError:
        return RunnableConfig()


def _extract_usage(message: AIMessage) -> dict[str, int]:
    """Return input/output/cached token counts from a message's usage metadata.

    Reads ``message.usage_metadata`` (the canonical LangChain shape) and falls
    back to ``response_metadata.usage_metadata`` for the provider SDK versions
    that only populate that. ``cached_tokens`` comes from
    ``input_token_details.cache_read`` or — when the provider surfaces it
    separately — ``cached_content_token_count``. Missing fields default to 0.
    """
    usage = getattr(message, "usage_metadata", None) or {}
    resp_meta = getattr(message, "response_metadata", None) or {}
    resp_usage = resp_meta.get("usage_metadata") or {}

    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cached_tokens = int((usage.get("input_token_details") or {}).get("cache_read") or 0)

    # Each field falls back independently. Gating the output fallback behind a
    # missing *input* count (as this once did) silently dropped output tokens —
    # and their cost — from every message that reported only one of the two.
    # Both `prompt_token_count`/`candidates_token_count` (provider-native shape)
    # and the LangChain-normalised keys are accepted.
    if not input_tokens:
        input_tokens = int(
            resp_usage.get("prompt_token_count", resp_usage.get("input_tokens", 0)) or 0
        )
    if not output_tokens:
        output_tokens = int(
            resp_usage.get("candidates_token_count", resp_usage.get("output_tokens", 0)) or 0
        )
    if not cached_tokens:
        cached_tokens = int(resp_usage.get("cached_content_token_count") or 0)

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
    }


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
      ceiling is exhausted (see :func:`get_budget_stop_reason`).
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
        self._start_ts: dict[str, float] = {}

    # --- helpers ---------------------------------------------------------

    def _thread_id(self, config: RunnableConfig) -> str:
        configurable = agent_configurable(config)
        return str(configurable.get("thread_id") or configurable.get("stream_id") or "unknown")

    def _next_step(self, thread_id: str) -> int:
        n = self._step_counts.get(thread_id, 0) + 1
        self._step_counts[thread_id] = n
        return n

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
        config = _current_config()
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
        """
        configurable = agent_configurable(_current_config())
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
            stop_reason = await get_budget_stop_reason(
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
            stop_reason = None

        if stop_reason is not None:
            log.warning(
                "budget_stop",
                event_name="budget_stop",
                agent_name=self.agent_name,
                user_id=user_id,
                plan_type=plan_raw,
                root_request_id=root_request_id,
            )
            return ModelResponse(result=[AIMessage(content=stop_reason)])

        return await handler(request)

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

        usage = _extract_usage(ai_msg)
        input_tokens = usage["input_tokens"]
        output_tokens = usage["output_tokens"]
        cached_tokens = usage["cached_tokens"]

        config = _current_config()
        configurable = agent_configurable(config)
        thread_id = self._thread_id(config)
        lane = ModelLane.from_configurable(configurable.get(LANE_FIELD_ID))
        model_name = (lane.model if lane else None) or "unknown"
        provider = lane.provider if lane else "unknown"
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
        root_request_id = configurable.get("root_request_id")
        total_cost = await record_llm_call(
            user_id=str(user_id) if user_id else None,
            model_name=str(model_name),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            root_request_id=str(root_request_id) if root_request_id else None,
            charge_to_budget=True,
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
        prior_cost = float(prior.get("cost_usd") or 0.0)

        agg_input = prior_input + input_tokens
        agg_output = prior_output + output_tokens
        agg_cached = prior_cached + cached_tokens
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
            cost_usd=total_cost,
            step_index=step_index,
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
        thread_id = self._thread_id(_current_config())
        self._start_ts[thread_id] = time.monotonic()
        return None

    def after_model(self, state: AgentState[Any], runtime: Runtime[Any]) -> dict[str, Any] | None:
        del state, runtime
        # Cost calc is async-only; in sync mode we still want the HWM signal.
        thread_id = self._thread_id(_current_config())
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
