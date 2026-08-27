"""Pricing + recording for a single model call — the one write both metering
routes share.

Two seams produce LLM spend and neither can see the other:

- ``LLMAccountingMiddleware`` for everything that runs through an agent graph
  (chat, workflows, bots, voice, subagents), which also passes
  ``root_request_id`` so the call counts toward the per-request token ceiling.
  This route CHARGES the user's day/month budget windows — it is work the user
  actively asked for.
- ``ainvoke_structured`` for auxiliary one-shot calls (memory
  extraction/reconcile/consolidation, follow-ups, onboarding, workflow
  generation, …), which never reach the middleware. This route records spend
  for COGS observability only (``charge_to_budget=False``) — background work
  must never consume the user's allowance.

Both call :func:`record_llm_call`, so a call is priced and recorded identically
no matter where it originates; only whether it counts against the budget
differs, and each caller states that explicitly. Lives in its own module
because ``cost_budget`` cannot import ``config.model_pricing`` — that pulls in
``app.decorators``, which imports ``cost_budget`` right back.
"""

from typing import TypedDict

from langchain_core.messages import AIMessage

from app.config.model_pricing import calculate_token_cost
from app.constants.llm import UNKNOWN_MODEL_NAME
from app.constants.log_tags import LogTag
from app.services.cost_budget import record_model_call_usage
from shared.py.wide_events import log


class TokenUsage(TypedDict):
    """The four token counts every metering route prices a call from."""

    input_tokens: int
    output_tokens: int
    cached_tokens: int
    reasoning_tokens: int


async def record_llm_call(
    *,
    user_id: str | None,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    reasoning_tokens: int = 0,
    root_request_id: str | None = None,
    charge_to_budget: bool,
) -> float:
    """Price one model call and record its spend + tokens. Returns the USD cost.

    ``cached_tokens`` is the subset of ``input_tokens`` that hit the provider's
    prompt cache — billed at the discounted rate, not free. ``reasoning_tokens``
    is the subset of ``output_tokens`` spent on hidden thinking, when the
    provider reports it (not separately priced — already billed as output).
    Both ride alongside the cost into the durable rollup so a mispriced call
    can be re-derived from raw usage after the fact. Omit ``root_request_id``
    for work that is not bounded by a single agent tree. ``charge_to_budget``
    is required so every call site states whether this spend counts against
    the user's allowance (agent-graph work the user asked for) or is auxiliary
    background COGS (recorded durably, never charged). Fail-open: a pricing or
    write failure degrades cost to 0.0 and never fails a model call that
    already succeeded.
    """
    try:
        cost = calculate_token_cost(
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
        )
        total_cost = float(cost.get("total_cost", 0.0))
    except Exception as e:
        # Pricing is pure computation over a model lookup — a failure here is an
        # unexpected bug (bad/missing pricing entry), not an infra blip, so it is
        # surfaced loudly and alertably. We still return 0.0 rather than raising:
        # the provider call already completed and charged, and raising would fail
        # the user's turn for a metering bug. The dropped spend is greppable via
        # this event so the budget under-count is visible, not silent.
        log.error(
            f"{LogTag.AGENT} Token cost calc failed — spend recorded as $0 "
            "(budget will under-count this call)",
            model=model_name,
            error=str(e),
            error_type=type(e).__name__,
        )
        total_cost = 0.0

    try:
        await record_model_call_usage(
            user_id,
            total_cost,
            root_request_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            reasoning_tokens=reasoning_tokens,
            charge_to_budget=charge_to_budget,
        )
    except Exception as e:
        # Infra fail-open per the cost-budget module's documented degradation
        # philosophy (a Redis blip must never fail an already-completed call).
        # record_model_call_usage already fails open per-op internally; this is
        # the outer backstop.
        log.warning(
            f"{LogTag.AGENT} Cost/token budget recording failed (failing open)",
            error=str(e),
            error_type=type(e).__name__,
        )

    return total_cost


def extract_message_usage(message: AIMessage) -> TokenUsage:
    """Return input/output/cached/reasoning token counts from a message's usage metadata.

    Reads ``message.usage_metadata`` (the canonical LangChain shape) and falls
    back to ``response_metadata.usage_metadata`` for the provider SDK versions
    that only populate that. ``cached_tokens`` comes from
    ``input_token_details.cache_read`` or — when the provider surfaces it
    separately — ``cached_content_token_count``. ``reasoning_tokens`` (a
    subset of ``output_tokens`` spent on hidden thinking) comes from
    ``output_token_details.reasoning``; not every provider/model returns it.
    Missing fields default to 0.
    """
    usage = getattr(message, "usage_metadata", None) or {}
    resp_meta = getattr(message, "response_metadata", None) or {}
    resp_usage = resp_meta.get("usage_metadata") or {}

    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cached_tokens = int((usage.get("input_token_details") or {}).get("cache_read") or 0)
    reasoning_tokens = int((usage.get("output_token_details") or {}).get("reasoning") or 0)

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

    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        reasoning_tokens=reasoning_tokens,
    )


def extract_message_model(message: AIMessage) -> str:
    """The model the provider says served this call, or ``UNKNOWN_MODEL_NAME``.

    For the one seam that cannot reach the lane: ``lane`` imports ``client``, so
    ``client`` cannot import ``ModelLane`` back. Everywhere else resolves the
    lane at the call site, the way ``accounting`` does.
    """
    resp_meta = getattr(message, "response_metadata", None) or {}
    return str(resp_meta.get("model_name") or "") or UNKNOWN_MODEL_NAME


def extract_generation_id(message: AIMessage) -> str | None:
    """The upstream generation id for this call, when the provider returned one.

    This is the ONLY handle we have on *which upstream served the request*.
    OpenRouter names the serving upstream in a ``provider`` response field, but
    ``ChatOpenRouter`` keeps only ``id`` / ``cost`` / ``system_fingerprint`` /
    ``native_finish_reason`` and stamps ``model_provider`` as the literal
    ``"openrouter"`` — so the aggregator's own name reaches us and the upstream's
    never does. ``id`` does survive both paths (``_create_chat_result`` puts it in
    ``llm_output``, which ``langchain_core`` merges into ``response_metadata``;
    ``_astream``/``_stream`` set ``generation_info["id"]`` directly), and it
    resolves to the serving upstream through OpenRouter's generation-metadata
    endpoint without spending a model call.

    Without it, a request that reports zero cached tokens is ambiguous: it may
    have landed on a different upstream (which holds no warm prefix at all) or
    the prompt prefix may have genuinely broken. Those have opposite fixes, so
    the id is what keeps a cache regression from being diagnosed by guesswork.
    """
    resp_meta = getattr(message, "response_metadata", None) or {}
    return str(resp_meta.get("id") or "") or None
