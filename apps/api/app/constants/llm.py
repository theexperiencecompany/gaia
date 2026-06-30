DEFAULT_LLM_PROVIDER = "gemini"

# How often the messages DeltaChannel writes a full snapshot blob (every Nth
# update). Between snapshots only per-step deltas are persisted, so checkpoint
# storage grows ~O(N) instead of the O(N²) of full-snapshot channels. Lower =
# more storage but faster thread reconstruction; higher = less storage but
# deeper delta replay on resume.
MESSAGES_SNAPSHOT_FREQUENCY = 50

# Runaway loops are the main driver of long, expensive traces; capping tail
# risk keeps p95 cost predictable. Legitimate tasks that need more steps
# should split work across handoffs rather than chew through recursion budget.
AGENT_RECURSION_LIMIT = 40  # Main agent graphs (comms, executor, provider subagents)
SUBAGENT_RECURSION_LIMIT = 15  # Spawned subagents (spawn_subagent tool loop)
# Emit a ``recursion_high_water_mark`` wide event when a run uses ≥80% of
# its limit so we can tune the cap from real traffic.
RECURSION_HWM_FRACTION = 0.80
# Context window of the default model below, in input tokens. The summarization /
# compaction middleware trigger on a fraction of this, and get_default_llm() feeds
# it to the model's profile (LangChain has no profile for newer models). Update it
# whenever DEFAULT_GEMINI_MODEL_NAME changes.
DEFAULT_MAX_TOKENS = 1_000_000
# Changing the default model is high blast radius — it is NOT just a string. Before
# you do, confirm for the new model:
#   - context window  -> update DEFAULT_MAX_TOKENS above (else fractional-token
#     middleware fails to build and the whole agent graph dies; see get_default_llm)
#   - pricing entry    -> app/config/model_pricing.py
#   - it's multimodal if vision/file tools rely on it
# Direct Gemini API model name.
DEFAULT_GEMINI_MODEL_NAME = "gemini-3.1-flash-lite"
# Default model for free / unspecified configs — always the Gemini model above.
DEFAULT_MODEL_NAME = DEFAULT_GEMINI_MODEL_NAME
DEFAULT_GROK_MODEL_NAME = "x-ai/grok-4.3"

# Per-plan model policy (hardcoded; not user-selectable). Free accounts run the
# default Gemini model above; every paid (non-free) plan runs a more capable
# model via OpenRouter.
PAID_MODEL_PROVIDER = "openrouter"
PAID_MODEL_NAME = "z-ai/glm-5.2"

# GLM 5.2's first-party (z-ai) lane exposes a 1M-token context window and a 131k
# output ceiling. Cap output well under that; the summarization / compaction
# middleware keeps input bounded (compaction at 0.40, summary at 0.60 of the
# window), so 64k of output leaves ample headroom for the prompt.
OPENROUTER_MAX_OUTPUT_TOKENS = 64_000

# Default reasoning effort for OpenRouter thinking models (executor + subagents),
# passed to ChatOpenRouter's native `reasoning` field.
OPENROUTER_REASONING = {"effort": "medium"}
# Pin the paid model to the first-party "z-ai" provider on OpenRouter. Without
# this, OpenRouter may load-balance z-ai/glm-5.2 across resellers (DeepInfra,
# Together, Parasail, etc.) whose shared pools get rate-limited upstream (429). `only`
# forces the first-party lane. Passed via ChatOpenRouter's `model_kwargs` (the
# OpenRouter `provider` routing param) and inherited by child agents via
# agent_helpers._inherit_from_parent_configurable so subagents stay on the same lane.
PAID_MODEL_PROVIDER_SLUG = "z-ai"
PAID_MODEL_MODEL_KWARGS = {"provider": {"only": [PAID_MODEL_PROVIDER_SLUG]}}
# Comms-specific reasoning: "low" instead of the executor's "medium". Comms is
# mostly routing/ack work, so the reasoning budget is most useful for the executor's
# tool selection. GLM 5.2 also documents "high"/"xhigh" efforts — revisit these
# levels if comms routing or executor tool-selection quality needs more headroom.
COMMS_REASONING = {"effort": "low"}

# OpenRouter app attribution (https://openrouter.ai/docs/app-attribution). The
# OpenRouter client surfaces these as the HTTP-Referer / X-Title /
# X-OpenRouter-Categories headers so GAIA appears on OpenRouter's app rankings.
# The referer URL is the public site (settings.FRONTEND_URL); title + categories
# are fixed app identity.
OPENROUTER_APP_TITLE = "GAIA"
OPENROUTER_APP_CATEGORIES = ["personal-agent", "general-chat"]

# DEV-ONLY model menu (ENV=development). The dev chat-header selector sends one of
# these stable ids per role (comms / executor); the backend pins the matching model.
# `reasoning` flags whether the model is an OpenRouter reasoning model — effort is
# applied per-role at override time (comms -> COMMS_REASONING, executor ->
# OPENROUTER_REASONING). Gemini models route direct via the "gemini" provider and
# ignore OpenRouter `model_kwargs`/`reasoning`. This menu is NEVER used in production.
DEV_MODEL_OPTIONS: dict[str, dict] = {
    "minimax-m3": {
        "provider": "openrouter",
        "model": "minimax/minimax-m3",
        "model_kwargs": {"provider": {"only": ["minimax"]}},
        "reasoning": True,
    },
    "glm-5.2": {
        "provider": "openrouter",
        "model": "z-ai/glm-5.2",
        "model_kwargs": {"provider": {"only": ["z-ai"]}},
        "reasoning": True,
    },
    "gemini-3.5-flash": {
        "provider": "openrouter",
        "model": "google/gemini-3.5-flash",
        "model_kwargs": None,
        "reasoning": False,
    },
    "deepseek-v4": {
        "provider": "openrouter",
        "model": "deepseek/deepseek-v4-pro",
        "model_kwargs": None,
        "reasoning": False,
    },
    "gemini-3.1-flash-lite": {
        "provider": "gemini",
        "model": "gemini-3.1-flash-lite",
        "model_kwargs": None,
        "reasoning": False,
    },
}
