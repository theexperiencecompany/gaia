"""Pricing + recording for a single model call — the one write both metering
routes share.

Two seams produce LLM spend and neither can see the other:

- ``LLMAccountingMiddleware`` for everything that runs through an agent graph
  (chat, workflows, bots, voice, subagents), which also passes
  ``root_request_id`` so the call counts toward the per-request token ceiling.
- ``ainvoke_structured`` for auxiliary one-shot calls (memory
  extraction/reconcile/consolidation, follow-ups, onboarding, workflow
  generation, …), which never reach the middleware.

Both call :func:`record_llm_call`, so a call is priced and recorded identically
no matter where it originates. Lives in its own module because
``cost_budget`` cannot import ``config.model_pricing`` — that pulls in
``app.decorators``, which imports ``cost_budget`` right back.
"""

from app.config.model_pricing import calculate_token_cost
from app.constants.log_tags import LogTag
from app.services.cost_budget import record_model_call_usage
from shared.py.wide_events import log


async def record_llm_call(
    *,
    user_id: str | None,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    root_request_id: str | None = None,
) -> float:
    """Price one model call and record its spend. Returns the USD cost.

    ``cached_tokens`` is the subset of ``input_tokens`` that hit the provider's
    prompt cache — billed at the discounted rate, not free. Omit
    ``root_request_id`` for work that is not bounded by a single agent tree.
    Fail-open: a pricing or write failure degrades to 0.0 and never fails a
    model call that already succeeded.
    """
    try:
        cost = await calculate_token_cost(
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
        )
        total_cost = float(cost.get("total_cost", 0.0))
    except Exception as e:
        log.warning(f"{LogTag.AGENT} Token cost calc failed for {model_name}: {e}")
        total_cost = 0.0

    try:
        await record_model_call_usage(
            user_id, total_cost, root_request_id, input_tokens + output_tokens
        )
    except Exception as e:
        log.warning(f"{LogTag.AGENT} Cost/token budget recording failed: {e}")

    return total_cost
