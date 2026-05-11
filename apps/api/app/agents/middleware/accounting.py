"""
LLM Call Accounting Middleware.

Emits a structured ``llm_call`` wide event after every model invocation with
input/cached/output tokens, credits charged, step index, and agent name. Also
emits ``recursion_high_water_mark`` when a run has consumed ≥80% of its
recursion limit so we can tune the cap from real data.

This middleware is a prerequisite for credit enforcement (CREDITS_PLAN.md
phase 2) but explicitly does NOT decrement credits or gate calls today. The
``@before_model`` hook is a no-op stub; turning it on in a later phase only
requires flipping the gating logic.

Runs as a LangChain :class:`AgentMiddleware` via `create_agent(middleware=...)`.
"""

import time
from typing import Any, Optional

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime, get_config

from app.config.model_pricing import calculate_token_cost
from app.constants.llm import AGENT_RECURSION_LIMIT, RECURSION_HWM_FRACTION
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
    """Return (input, cached, output) token counts from a message's usage.

    Handles both ``message.usage_metadata`` (the canonical LangChain shape)
    and legacy ``response_metadata.usage`` payloads. ``cached_tokens`` comes
    from ``input_token_details.cache_read`` or — when the underlying provider
    surfaces it separately — ``cached_content_token_count``. Missing fields
    default to 0.
    """
    usage = getattr(message, "usage_metadata", None) or {}
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)

    details = usage.get("input_token_details") or {}
    cached_tokens = int(details.get("cache_read", 0) or 0)

    # Some provider SDK versions surface cache reads under different keys.
    if not cached_tokens:
        resp_meta = getattr(message, "response_metadata", None) or {}
        provider_usage = resp_meta.get("usage_metadata") or {}
        cached_tokens = int(provider_usage.get("cached_content_token_count", 0) or 0)

    if not input_tokens:
        resp_meta = getattr(message, "response_metadata", None) or {}
        resp_usage = resp_meta.get("usage_metadata") or {}
        # Both `prompt_token_count`/`candidates_token_count` (provider-native
        # shape) and the LangChain-normalised keys are accepted.
        input_tokens = int(
            resp_usage.get("prompt_token_count", resp_usage.get("input_tokens", 0)) or 0
        )
        output_tokens = output_tokens or int(
            resp_usage.get("candidates_token_count", resp_usage.get("output_tokens", 0))
            or 0
        )

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
    }


def _latest_ai_message(messages: list[Any]) -> Optional[AIMessage]:
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
    - ``@before_model``: stubbed no-op today. Will gate credit-exhausted users
      in CREDITS_PLAN.md phase 2 via LangGraph's native
      ``@hook_config(can_jump_to=["end"])`` mechanism — no exception raising.
    """

    def __init__(
        self, agent_name: str, recursion_limit: int = AGENT_RECURSION_LIMIT
    ) -> None:
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
        configurable = config.get("configurable", {}) or {}
        return str(
            configurable.get("thread_id") or configurable.get("stream_id") or "unknown"
        )

    def _next_step(self, thread_id: str) -> int:
        n = self._step_counts.get(thread_id, 0) + 1
        self._step_counts[thread_id] = n
        return n

    # --- hooks -----------------------------------------------------------

    async def abefore_model(
        self,
        state: AgentState[Any],
        runtime: Runtime[Any],
    ) -> Optional[dict[str, Any]]:
        """Pre-call hook. Stub today.

        Credit gating will flip on here in CREDITS_PLAN.md phase 2. When
        enabled, return ``{"messages": [AIMessage("Credit limit reached…")]}``
        plus the ``jump_to="end"`` marker — the native LangGraph escape
        hatch — instead of raising an exception.
        """
        del state, runtime  # state not consulted in this pre-call hook yet
        config = _current_config()
        thread_id = self._thread_id(config)
        self._start_ts[thread_id] = time.monotonic()
        return None

    async def aafter_model(
        self,
        state: AgentState[Any],
        runtime: Runtime[Any],
    ) -> Optional[dict[str, Any]]:
        """Emit ``llm_call`` wide event after the model produces a response."""
        del runtime  # unused — config is fetched from the graph context var
        messages = (
            state.get("messages")
            if isinstance(state, dict)
            else getattr(state, "messages", [])
        )
        ai_msg = _latest_ai_message(messages or [])
        if ai_msg is None:
            return None

        usage = _extract_usage(ai_msg)
        input_tokens = usage["input_tokens"]
        output_tokens = usage["output_tokens"]
        cached_tokens = usage["cached_tokens"]

        config = _current_config()
        configurable = config.get("configurable", {}) or {}
        thread_id = self._thread_id(config)
        model_name = (
            configurable.get("model_name") or configurable.get("model") or "unknown"
        )
        provider = configurable.get("provider", "unknown")
        user_id = configurable.get("user_id")

        # Cost in USD. Pass full input_tokens + cached_tokens so the cached
        # subset is billed at the discounted rate, not free.
        try:
            cost = await calculate_token_cost(
                model_name=str(model_name),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
            )
            total_cost = float(cost.get("total_cost", 0.0))
        except Exception as e:
            log.warning(f"Token cost calc failed for {model_name}: {e}")
            total_cost = 0.0

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
    def before_model(
        self, state: AgentState[Any], runtime: Runtime[Any]
    ) -> Optional[dict[str, Any]]:
        del state, runtime
        thread_id = self._thread_id(_current_config())
        self._start_ts[thread_id] = time.monotonic()
        return None

    def after_model(
        self, state: AgentState[Any], runtime: Runtime[Any]
    ) -> Optional[dict[str, Any]]:
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
