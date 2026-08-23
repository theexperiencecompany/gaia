"""Model pricing for token cost calculation — the rate card ships in code.

Pricing previously lived in the ``ai_models`` Mongo collection, synced by hand
via ``scripts/seed_models.py``. Nothing enforced the sync, so prod drifted: the
vision/memory model's row went missing and every one of its calls was priced at
DEFAULT_PRICING (~10x its real input rate) with only an error log to show for
it. Models are constants in ``constants/llm.py``; their prices now live beside
them, so a rate changes in the same reviewed deploy as the model id, and the
unit suite fails if a runtime-referenced model has no rate.
"""

from typing import NamedTuple

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

# Default cached-input price as a fraction of full input price when the
# model entry doesn't specify one. Matches Gemini's standard implicit-cache
# discount.
DEFAULT_CACHED_INPUT_FRACTION = 0.25


class ModelPricing(NamedTuple):
    input_cost_per_1k: float
    output_cost_per_1k: float
    cached_input_cost_per_1k: float = 0.0


# Default fallback pricing for unknown models. Cached-input is 25% of input.
DEFAULT_PRICING = ModelPricing(
    input_cost_per_1k=0.001,
    output_cost_per_1k=0.002,
    cached_input_cost_per_1k=0.001 * DEFAULT_CACHED_INPUT_FRACTION,
)

# Per-1k USD rates by model id, from each provider's published listing
# (https://openrouter.ai/api/v1/models for the OpenRouter-served ids). Keys are
# the ids the runtime actually passes to get_model_pricing — the constants in
# constants/llm.py plus the aux routing alias. Nothing reconciles these against
# the live listings: re-check the rates by hand whenever a model id here is
# added or re-pointed, and keep tests/unit/config/test_model_pricing.py's
# runtime-coverage test green so a referenced-but-unpriced model cannot ship.
MODEL_PRICING: dict[str, ModelPricing] = {
    # DEFAULT_MODEL_NAME / PAID_MODEL_NAME — the graph lane on every tier.
    "deepseek/deepseek-v4-flash-0731": ModelPricing(
        input_cost_per_1k=0.00014,
        output_cost_per_1k=0.00028,
        cached_input_cost_per_1k=0.000028,
    ),
    # MEMORY_MODEL_NAME / VISION_MODEL_NAME — deliberately a different provider
    # than the graph lane (see constants/llm.py for the cache-collision reason).
    "gemini-3.1-flash-lite": ModelPricing(
        input_cost_per_1k=0.0001,
        output_cost_per_1k=0.0004,
        cached_input_cost_per_1k=0.000025,
    ),
    # AUX_MODEL_NAME — "DeepSeek V4 Flash 0423" (Apr 2026), not the "0731"
    # revision the graph runs, so aux calls get a separate prompt-cache
    # namespace. Two ids, two rate cards: 0423 is roughly 0.46x 0731's input
    # rate, so pricing the aux lane at 0731's rate would OVER-count aux COGS by
    # ~2.2x. 20% cached-input fraction, matching OpenRouter's listing.
    "deepseek/deepseek-v4-flash": ModelPricing(
        input_cost_per_1k=0.00006426,
        output_cost_per_1k=0.00012852,
        cached_input_cost_per_1k=0.000012852,
    ),
}


def get_model_pricing(model_name: str) -> ModelPricing:
    """The rate card for ``model_name``, or DEFAULT_PRICING — loudly — when the
    id was never registered above."""
    pricing = MODEL_PRICING.get(model_name)
    if pricing is not None:
        return pricing
    # A model id missing from the table is priced at DEFAULT_PRICING, which is
    # not its real rate — so it must never pass quietly.
    log.error(
        f"{LogTag.AGENT} model missing from pricing table — priced at DEFAULT_PRICING",
        model_name=model_name,
    )
    return DEFAULT_PRICING


def calculate_token_cost(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int | None = 0,
) -> dict[str, float]:
    """Calculate the cost in USD for token usage.

    ``input_tokens`` is the total prompt size; ``cached_tokens`` is the
    subset that hit the provider's prompt cache (billed at the discounted
    rate). Returns ``input_cost`` (uncached portion only),
    ``cached_input_cost``, ``output_cost`` and ``total_cost``.
    """
    pricing = get_model_pricing(model_name)

    cached = max(int(cached_tokens or 0), 0)
    cached = min(cached, max(int(input_tokens), 0))
    uncached = max(int(input_tokens) - cached, 0)

    input_cost = (uncached / 1000) * pricing.input_cost_per_1k
    cached_input_cost = (cached / 1000) * pricing.cached_input_cost_per_1k
    output_cost = (output_tokens / 1000) * pricing.output_cost_per_1k
    total_cost = input_cost + cached_input_cost + output_cost

    return {
        "input_cost": round(input_cost, 6),
        "cached_input_cost": round(cached_input_cost, 6),
        "output_cost": round(output_cost, 6),
        "total_cost": round(total_cost, 6),
    }
