"""
Model pricing configuration for token cost calculation.
Uses model_service to fetch models with caching support.
"""

from typing import NamedTuple

from app.services.model_service import get_model_by_id
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


async def get_model_pricing(model_name: str) -> ModelPricing:
    """
    Get pricing info for a specific model from the model service with caching.
    Handles model name variants (e.g., gpt-4o-mini-2024-07-18 -> gpt-4o-mini).

    Args:
        model_name: Name of the model (may include version suffix)

    Returns:
        ModelPricing with cost per 1k tokens
    """
    try:
        # Try exact match first using model_service (uses caching)
        model = await get_model_by_id(model_name)

        if model:
            input_cost = getattr(model, "pricing_per_1k_input_tokens", None)
            output_cost = getattr(model, "pricing_per_1k_output_tokens", None)
            cached_input_cost = getattr(model, "pricing_per_1k_cached_input_tokens", None)

            if input_cost is not None and output_cost is not None:
                if cached_input_cost is None:
                    cached_input_cost = float(input_cost) * DEFAULT_CACHED_INPUT_FRACTION
                return ModelPricing(
                    input_cost_per_1k=float(input_cost),
                    output_cost_per_1k=float(output_cost),
                    cached_input_cost_per_1k=float(cached_input_cost),
                )

        # Fallback to default pricing
        return DEFAULT_PRICING

    except Exception as e:
        log.error(f"Error fetching pricing for model {model_name}: {e}")
        return DEFAULT_PRICING


async def calculate_token_cost(
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
    pricing = await get_model_pricing(model_name)

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
