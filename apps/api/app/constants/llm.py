DEFAULT_LLM_PROVIDER = "gemini"
# Runaway loops are the main driver of long, expensive traces; capping tail
# risk keeps p95 cost predictable. Legitimate tasks that need more steps
# should split work across handoffs rather than chew through recursion budget.
AGENT_RECURSION_LIMIT = 40  # Main agent graphs (comms, executor, provider subagents)
SUBAGENT_RECURSION_LIMIT = 15  # Spawned subagents (spawn_subagent tool loop)
# Emit a ``recursion_high_water_mark`` wide event when a run uses ≥80% of
# its limit so we can tune the cap from real traffic.
RECURSION_HWM_FRACTION = 0.80
DEFAULT_MAX_TOKENS = 1_000_000
DEFAULT_MODEL_NAME = "gemini-3.1-flash-lite"
# Direct Gemini API model
DEFAULT_GEMINI_MODEL_NAME = "gemini-3.1-flash-lite"
DEFAULT_GROK_MODEL_NAME = "x-ai/grok-4.3"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Per-plan model policy (hardcoded; not user-selectable). Free accounts run the
# default Gemini model above; every paid (non-free) plan runs a more capable
# model via OpenRouter.
PAID_MODEL_PROVIDER = "openrouter"
PAID_MODEL_NAME = "minimax/minimax-m3"

# MiniMax M3's 524288-token context is SHARED between input and output, and
# OpenRouter validates ``input + max_tokens <= context`` up front. Reserving the
# model's full 512k output ceiling left ~12k for the prompt → 400 over-context
# errors. Cap output generously but well under the window; the summarization /
# compaction middleware keeps input bounded (compaction at 0.40, summary at 0.60
# of the window), so 64k of output leaves ample headroom for the prompt.
OPENROUTER_MAX_OUTPUT_TOKENS = 64_000

# Reasoning config shared by all OpenRouter (thinking) models.
OPENROUTER_REASONING = {"effort": "medium"}
# Default OpenRouter request body: reasoning on, provider auto-routed by OpenRouter.
OPENROUTER_DEFAULT_EXTRA_BODY = {"reasoning": OPENROUTER_REASONING}
# Pin the paid model to the first-party "minimax" provider on OpenRouter. Without
# this, OpenRouter load-balances minimax/minimax-m3 across resellers (Parasail,
# Together, Morph, …) whose shared non-BYOK pools get rate-limited upstream (429).
# `only` forces the first-party lane and disables fallback to those resellers.
PAID_MODEL_PROVIDER_SLUG = "minimax"
PAID_MODEL_EXTRA_BODY = {
    "reasoning": OPENROUTER_REASONING,
    "provider": {"only": [PAID_MODEL_PROVIDER_SLUG]},
}
