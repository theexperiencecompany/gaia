"""Model pricing for token cost calculation — the rate card ships in code.

Pricing previously lived in the ai_models Mongo collection, synced by hand
via scripts/seed_models.py. Nothing enforced the sync, so prod drifted: the
vision/memory model's row went missing and every one of its calls was priced at
DEFAULT_PRICING (~10x its real input rate) with only an error log to show for
it. Models are constants in constants/llm.py; their prices now live beside
them, so a rate changes in the same reviewed deploy as the model id, and the
unit suite fails if a runtime-referenced model has no rate.
"""

from typing import NamedTuple

from app.config.settings import settings
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

# Per-1k USD rates by model id (https://openrouter.ai/api/v1/models for the
# OpenRouter-served ids). Nothing reconciles these against the live listings —
# re-check by hand when a model id here is added or re-pointed.
MODEL_PRICING: dict[str, ModelPricing] = {
    # DEFAULT_MODEL_NAME / PAID_MODEL_NAME — the graph lane on every tier.
    # Live 2026-09-20: $0.04/$0.08/$0.016 per 1M in/out/cached.
    "deepseek/deepseek-v4-flash-0731": ModelPricing(
        input_cost_per_1k=0.00004,
        output_cost_per_1k=0.00008,
        cached_input_cost_per_1k=0.000016,
    ),
    # HIL_JUDGE_MODEL_NAME — the approval gate's judge (+ eval winner 42/50) —
    # and BROWSER_USE_JEV_TEXT_MODEL, the text helper that writes typed values
    # for Jev's decisions. Live 2026-09-20: $0.30/$2.50/$0.03 per 1M in/out/cached.
    "google/gemini-3.5-flash-lite": ModelPricing(
        input_cost_per_1k=0.0003,
        output_cost_per_1k=0.0025,
        cached_input_cost_per_1k=0.00003,
    ),
    # MEMORY_MODEL_NAME / VISION_MODEL_NAME — deliberately a different provider
    # than the graph lane (see constants/llm.py for the cache-collision reason).
    "gemini-3.1-flash-lite": ModelPricing(
        input_cost_per_1k=0.0001,
        output_cost_per_1k=0.0004,
        cached_input_cost_per_1k=0.000025,
    ),
    # "DeepSeek V4 Flash 0423" (Apr 2026): deprecated because its provider pool
    # can't cache or hold session affinity for tool-carrying requests. Row stays
    # so historical llm_call events still meter at the rate actually served.
    "deepseek/deepseek-v4-flash": ModelPricing(
        input_cost_per_1k=0.00006426,
        output_cost_per_1k=0.00012852,
        cached_input_cost_per_1k=0.000012852,
    ),
    # BROWSER_USE_JEV_MODEL, TypeSafe's decision model, served by OpenRouter.
    # $0.042 per 1M input tokens, nothing for output (a decision returns choices,
    # not generated tokens). Confirmed billed 1.722e-05 for 410 in / 38 out tokens.
    "~typesafe/jev-latest": ModelPricing(
        input_cost_per_1k=0.000042,
        output_cost_per_1k=0.0,
        cached_input_cost_per_1k=0.0,
    ),
    # LOCAL DEV TESTING ONLY (DEV_LLM_MODEL=gpt-4.1-mini over the OpenAI custom
    # lane) - do not ship. OpenAI list price: $0.40/$1.60 per 1M in/out, $0.10 cached.
    "gpt-4.1-mini": ModelPricing(
        input_cost_per_1k=0.0004,
        output_cost_per_1k=0.0016,
        cached_input_cost_per_1k=0.0001,
    ),
}


def get_model_pricing(model_name: str) -> ModelPricing:
    """Return the rate card for model_name, or DEFAULT_PRICING (logged) if unregistered."""
    pricing = MODEL_PRICING.get(model_name)
    if pricing is not None:
        return pricing
    # OpenRouter routing variants ("model:nitro" sorts providers by throughput,
    # ":floor" by price) name the same model; its rate card is the base id's.
    base, _, variant = model_name.rpartition(":")
    if variant and base in MODEL_PRICING:
        return MODEL_PRICING[base]
    if _is_dev_custom_model(model_name):
        # Any id a developer points DEV_LLM_MODEL at: unpriced by design, and
        # has_rate_card still marks its cost estimated. An error per call was noise.
        return DEFAULT_PRICING
    # A model id missing from the table is priced at DEFAULT_PRICING, which is
    # not its real rate — so it must never pass quietly.
    log.error(
        f"{LogTag.AGENT} model missing from pricing table — priced at DEFAULT_PRICING",
        model_name=model_name,
    )
    return DEFAULT_PRICING


def _is_dev_custom_model(model_name: str) -> bool:
    """Whether model_name is the development-only custom endpoint's model (DEV_LLM_MODEL)."""
    return settings.ENV == "development" and model_name == settings.DEV_LLM_MODEL


def has_rate_card(model_name: str) -> bool:
    """Return True when the model has a real entry, rather than DEFAULT_PRICING."""
    return model_name in MODEL_PRICING


def calculate_token_cost(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int | None = 0,
) -> dict[str, float]:
    """Calculate the cost in USD for token usage.

    input_tokens is the total prompt size; cached_tokens is the
    subset that hit the provider's prompt cache (billed at the discounted
    rate). Returns input_cost (uncached portion only),
    cached_input_cost, output_cost and total_cost.
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
