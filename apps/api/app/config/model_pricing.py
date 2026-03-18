"""
Model pricing configuration for token cost calculation.
Uses model_service to fetch models with caching support.
"""

from typing import Dict, NamedTuple

from shared.py.wide_events import log
from app.services.model_service import get_model_by_id


class ModelPricing(NamedTuple):
    input_cost_per_1k: float  # Cost per 1k input tokens
    output_cost_per_1k: float  # Cost per 1k output tokens


# Default fallback pricing for unknown models
DEFAULT_PRICING = ModelPricing(input_cost_per_1k=0.001, output_cost_per_1k=0.002)


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

            if input_cost is not None and output_cost is not None:
                return ModelPricing(
                    input_cost_per_1k=float(input_cost),
                    output_cost_per_1k=float(output_cost),
                )

        # Fallback to default pricing
        return DEFAULT_PRICING

    except Exception as e:
        log.error(f"Error fetching pricing for model {model_name}: {e}")
        return DEFAULT_PRICING


async def calculate_token_cost(
    model_name: str, input_tokens: int, output_tokens: int
) -> Dict[str, float]:
    """
    Calculate the cost in USD (credits) for token usage using model pricing.

    Args:
        model_name: Name of the model used
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens

    Returns:
        Dict with input_cost, output_cost, and total_cost (in USD)
    """
    pricing = await get_model_pricing(model_name)

    input_cost = (input_tokens / 1000) * pricing.input_cost_per_1k
    output_cost = (output_tokens / 1000) * pricing.output_cost_per_1k
    total_cost = input_cost + output_cost

    return {
        "input_cost": round(input_cost, 6),
        "output_cost": round(output_cost, 6),
        "total_cost": round(total_cost, 6),
    }
