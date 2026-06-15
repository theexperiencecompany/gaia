"""Credit-system constants — the single source of truth for the credit unit.

A credit is GAIA's user-facing unit of AI compute. One credit equals
``CREDIT_VALUE_USD`` of raw provider cost, so credit burn always tracks real
cost: every LLM call is charged ``ceil(cost_usd / CREDIT_VALUE_USD)`` credits,
and discrete non-LLM actions are charged a fixed amount from
``ACTION_CREDIT_COSTS``.

Per-tier credit allotments live in ``app.config.rate_limits`` as the ``credits``
feature (one unified pool across chat, workflows, voice, and actions). Persistent
purchased credits (top-ups) are paid for via Dodo and held in our own grant
ledger (see ``credit_wallet_service``).
"""

import os

# 1 credit = $0.0001 of raw compute → 10,000 credits = $1.
CREDIT_VALUE_USD = 0.0001

# When True, out-of-credit users are blocked at the agent entry points. When
# False (shadow mode), credits are still metered but never block — for a safe
# rollout while real usage data is gathered.
CREDITS_ENFORCEMENT_ENABLED = os.getenv("CREDITS_ENFORCEMENT_ENABLED", "true").lower() == "true"

# Shown to the user (as a normal assistant message) when they're out of credits.
CREDIT_LIMIT_MESSAGE = (
    "You've used all your available credits for now. Your plan allotment resets "
    "daily and monthly — or you can upgrade your plan (or top up) to keep going."
)

# The single unified credit pool, registered as a feature in FEATURE_LIMITS.
CREDITS_FEATURE_KEY = "credits"

# Fixed credit price of discrete non-LLM actions, derived from provider cost
# (≈ provider_cost / CREDIT_VALUE_USD). LLM token cost is metered separately.
ACTION_CREDIT_COSTS: dict[str, int] = {
    "web_search": 100,  # ≈ $0.01 per search
    "image_generation": 500,  # ≈ $0.05 per image
    "deep_research": 1000,  # ≈ $0.10 external search/crawl (LLM tokens charged on top)
}

# Surface a warning to the user as they approach the cap.
CREDIT_WARN_THRESHOLDS: tuple[float, ...] = (0.75, 0.90, 1.0)

# Purchased top-up credits persist this long before expiring.
CREDIT_TOPUP_EXPIRY_DAYS = 365

# Top-up packs (Pro/Max only). Priced at ~2x raw cost (~50% margin): 1 credit
# costs $0.0001, so 50k credits = $5 cost, sold for $10. price_cents is USD.
CREDIT_TOPUP_PACKS: list[dict[str, object]] = [
    {"key": "small", "credits": 50_000, "price_cents": 1000, "name": "50,000 credits"},
    {"key": "medium", "credits": 150_000, "price_cents": 2800, "name": "150,000 credits"},
    {"key": "large", "credits": 500_000, "price_cents": 8500, "name": "500,000 credits"},
]
