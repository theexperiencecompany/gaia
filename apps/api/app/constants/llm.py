from typing import Any

from app.models.models_models import DevModelOption

# The ``configurable`` keys LangChain's own field resolution reads. Written at
# TWO definition sites (the Gemini lane's ConfigurableField and the OpenRouter
# lane's) and produced at a third (ModelLane.binding_keys), and nothing enforced
# that the three agreed — which is exactly how the Gemini and OpenRouter model
# ids ended up SWAPPED, silently resolving a different model than the config
# named. One definition, referenced from every site (Type Safety item 18).
MODEL_FIELD_ID = "model"
PROVIDER_FIELD_ID = "provider"
REASONING_FIELD_ID = "reasoning"
MODEL_KWARGS_FIELD_ID = "model_kwargs"

# The configurable key the whole resolved ModelLane rides under.
LANE_FIELD_ID = "lane"

GEMINI_PROVIDER = "gemini"
OPENROUTER_PROVIDER = "openrouter"

DEFAULT_LLM_PROVIDER = OPENROUTER_PROVIDER

# How often the messages DeltaChannel writes a full snapshot blob (every Nth
# update). Between snapshots only per-step deltas are persisted, so checkpoint
# storage grows ~O(N) instead of the O(N²) of full-snapshot channels. Lower =
# more storage but faster thread reconstruction; higher = less storage but
# deeper delta replay on resume.
MESSAGES_SNAPSHOT_FREQUENCY = 50

# Runaway loops are the main driver of long, expensive traces; capping tail
# risk keeps p95 cost predictable. Legitimate tasks that need more steps
# should split work across handoffs rather than chew through recursion budget.
AGENT_RECURSION_LIMIT = 40  # Comms + provider subagents (routing / focused work)
# The executor legitimately runs long multi-step tool loops (retrieve_tools ->
# handoff -> tool calls, frequently across several subagents), so 40 is too tight
# and truncates real work with GraphRecursionError. Both the graph's runtime
# recursion_limit and the accounting middleware's high-water-mark denominator read
# this, so enforcement and analytics stay in sync.
EXECUTOR_RECURSION_LIMIT = 100
SUBAGENT_RECURSION_LIMIT = 15  # Spawned subagents (spawn_subagent tool loop)
# The workflow authoring subagent only discovers integrations/triggers then emits
# JSON; it never executes. A handful of discovery calls is plenty, so it gets a
# tighter budget than a full agent. On hitting it the runner forces a final
# answer instead of crashing, so this doubles as the "stop wandering" bound.
WORKFLOW_SUBAGENT_RECURSION_LIMIT = 20
# Emit a ``recursion_high_water_mark`` wide event when a run uses ≥80% of
# its limit so we can tune the cap from real traffic.
RECURSION_HWM_FRACTION = 0.80
# When this few supersteps remain before the recursion limit, acall_model
# injects a wrap-up notice so the model finishes with a summary instead of
# dying mid-exploration on GraphRecursionError.
RECURSION_WRAPUP_THRESHOLD_STEPS = 6

# Per-tool-call execution timeout. A hung integration call previously hung the
# entire run forever (no timeout existed at any dispatch layer). Orchestration
# tools that legitimately run for minutes are exempt — they have their own
# lifecycle management (recursion caps, busy locks, subagent counters).
TOOL_EXECUTION_TIMEOUT_SECONDS = 120
TOOL_TIMEOUT_EXEMPT_TOOLS = frozenset(
    {
        "call_executor",
        "cancel_executor",
        "spawn_subagent",
        "handoff",
        "wait_for_subagents",
        "deep_research",
    }
)

# Attempts for the model-level transient-error retry before the caller falls back
# to the default model (see with_llm_retry in app/agents/llm/client.py).
LLM_RETRY_MAX_ATTEMPTS = 3

# Total wall-clock ceiling for one ainvoke_llm call — retries, backoff sleeps and the
# fallback attempt included. A backstop against a provider that accepts the connection
# and then never answers, which no retry can rescue because nothing ever raises.
#
# Sized for the slowest legitimate caller (onboarding intelligence, workflow generation,
# document analysis), NOT as a per-caller latency budget: a call on a user-blocking path
# should pass its own tighter value, the way the HIL gate passes
# HIL_LLM_TIMEOUT_SECONDS. Pass timeout=None to opt out entirely.
LLM_INVOKE_TIMEOUT_SECONDS = 120

# Near-deterministic default for every LLM call; creative tasks opt into more
# variation via get_default_llm(temperature=...).
DEFAULT_LLM_TEMPERATURE = 0.1

# Context window of the default model below, in input tokens. The summarization /
# compaction middleware trigger on a fraction of this, and get_default_llm() feeds
# it to the model's profile (LangChain has no profile for newer models). Update it
# whenever DEFAULT_MODEL_NAME changes.
# Known limitation: middleware is constructed at graph-build time, so the fractional
# triggers are denominated in THIS window even when a different chat model serves the
# request (e.g. the paid OpenRouter model or a dev-menu override).
DEFAULT_MAX_TOKENS = 1_000_000
# Changing the default model is high blast radius — it is NOT just a string. Before
# you do, confirm for the new model:
#   - context window  -> update DEFAULT_MAX_TOKENS above (else fractional-token
#     middleware fails to build and the whole agent graph dies; see get_default_llm)
#   - pricing entry    -> the `ai_models` collection (scripts/seed_models.py);
#     without one, calculate_token_cost falls back to DEFAULT_PRICING and the
#     cost budgets meter at the wrong rate
#   - it's multimodal if vision/file tools rely on it
# Default model for every tier and every auxiliary call, served over OpenRouter.
# Text-only: tool results carrying images are captioned for it rather than shown
# (see agents/llm/vision/capability.py).
DEFAULT_MODEL_NAME = "deepseek/deepseek-v4-flash-0731"
# Retained for the direct-Gemini lane, which is still selectable as a provider
# alternative and in the dev model menu — it is no longer the default.
DEFAULT_GEMINI_MODEL_NAME = "gemini-3.1-flash-lite"
DEFAULT_GROK_MODEL_NAME = "x-ai/grok-4.3"

# The model behind every image -> text call: the vision fallback for a lane that
# cannot take pixels (see vision/capability.py), plus the image-upload and
# file-summary paths, which produce text as their product and therefore always
# need it. Deliberately NOT tied to DEFAULT_MODEL_NAME: the default is chosen for
# cheap text and may be text-only, and a blind describer fails SILENTLY —
# describe_image degrades to None, so images would just stop being understood
# with nothing in the logs to say why. Direct Gemini is the one lane
# resolve_media_delivery treats as unconditionally multimodal.
VISION_MODEL_PROVIDER = GEMINI_PROVIDER
VISION_MODEL_NAME = DEFAULT_GEMINI_MODEL_NAME

# GAIA_SIM_MODE (see app/agents/llm/client.py): every model factory resolves to
# the local scripted stub (tools/llm-stub) at this address. The model name is a
# marker the stub ignores; the key satisfies client construction only.
SIM_STUB_BASE_URL = "http://localhost:9797/api/v1"
SIM_STUB_API_KEY = "sk-stub-dev"  # pragma: allowlist secret
SIM_STUB_MODEL_NAME = "gaia-sim-stub"

# Per-plan model policy (hardcoded; not user-selectable). Both tiers currently
# run the SAME model, so plan routing is a no-op on model choice and the pro
# monthly-budget degrade in resolve_lane has nothing to degrade to — kept in
# place deliberately, so re-pointing PAID_MODEL_NAME at a stronger model is the
# only change needed to make that guard bite again.
PAID_MODEL_PROVIDER = OPENROUTER_PROVIDER
PAID_MODEL_NAME = DEFAULT_MODEL_NAME

# Which OpenRouter models accept image input, straight from the live catalog's
# `architecture.input_modalities` — so vision support needs no per-model
# curation here. See app/agents/llm/model_catalog.py for the cache, and
# app/agents/llm/vision/ for how each lane then receives the media.
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_MODEL_CATALOG_TTL_SECONDS = 3600
OPENROUTER_MODEL_CATALOG_TIMEOUT_SECONDS = 10
# How long a failed catalog refresh is remembered. The catalog is consulted on
# the pre-model hook, so without a backoff an OpenRouter outage would cost every
# model call a full fetch timeout — turning a degraded dependency into an
# unusable product.
OPENROUTER_MODEL_CATALOG_RETRY_SECONDS = 300

# GLM 5.2's first-party (z-ai) lane exposes a 1M-token context window and a 131k
# output ceiling. Cap output well under that; the summarization / compaction
# middleware keeps input bounded (compaction at 0.40, summary at 0.60 of the
# window), so 64k of output leaves ample headroom for the prompt.
OPENROUTER_MAX_OUTPUT_TOKENS = 64_000

# Default reasoning effort for OpenRouter thinking models (executor + subagents),
# passed to ChatOpenRouter's native `reasoning` field.
OPENROUTER_REASONING: dict[str, Any] = {"effort": "medium"}
# Pin the paid model to the first-party "z-ai" provider on OpenRouter. Without
# this, OpenRouter may load-balance z-ai/glm-5.2 across resellers (DeepInfra,
# Together, Parasail, etc.) whose shared pools get rate-limited upstream (429). `only`
# forces the first-party lane. Passed via ChatOpenRouter's `model_kwargs` (the
# OpenRouter `provider` routing param) and inherited by child agents via
# agent_helpers._inherit_from_parent_configurable so subagents stay on the same lane.
PAID_MODEL_PROVIDER_SLUG = "deepseek"
PAID_MODEL_MODEL_KWARGS = {"provider": {"only": [PAID_MODEL_PROVIDER_SLUG]}}
# Comms-specific reasoning: "low" instead of the executor's "medium". Comms is
# mostly routing/ack work, so the reasoning budget is most useful for the executor's
# tool selection. GLM 5.2 also documents "high"/"xhigh" efforts — revisit these
# levels if comms routing or executor tool-selection quality needs more headroom.
COMMS_REASONING: dict[str, Any] = {"effort": "low"}

# Output cap for the env-defined custom dev provider (the "custom" entry below;
# endpoint/key/model all come from the DEV_LLM_* settings). 64k fits under the
# completion ceilings of the cheap lanes this is meant for (e.g. DeepSeek V4
# Flash caps at 65,536).
DEV_LLM_MAX_OUTPUT_TOKENS = 64_000

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
DEV_MODEL_OPTIONS: dict[str, DevModelOption] = {
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
    "deepseek-v4-flash": {
        # Pinned snapshot — same id also served by the cheap OpenRouter-compatible
        # lanes (e.g. Nous Research), so the custom endpoint below can run the
        # identical model for A/B-ing routes.
        "provider": "openrouter",
        "model": "deepseek/deepseek-v4-flash-0731",
        "model_kwargs": None,
        "reasoning": False,
    },
    "custom": {
        # The env-defined endpoint (DEV_LLM_* settings). `model` None = don't pin
        # one here; the client's own default (DEV_LLM_MODEL) serves the request.
        "provider": "custom",
        "model": None,
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

# --- Tier cost enforcement (free = usage walls, pro = abuse guards) --------------
# Hard ceiling on TOTAL tokens (input + output, summed across comms + executor +
# every subagent) a single request may consume before it is stopped mid-flight
# via the accounting middleware. Free = usage wall; pro is set high enough that
# only a runaway loop trips it — real work (full-inbox triage) must finish.
FREE_PER_REQUEST_TOKEN_CEILING = 300_000  # TUNE
PRO_PER_REQUEST_TOKEN_CEILING = 5_000_000  # TUNE

# Rolling daily USD cost budget. Free: a real usage wall — when the UTC day's
# cumulative cost reaches it, ALL chat is blocked until reset. Pro: an
# abuse-level burst guard only — a legitimate power user must never hit it.
#
# The budget covers what the user actively asks for: chat turns and the agent
# work they trigger. Auxiliary background spend (memory extraction/reconcile/
# consolidation, follow-up suggestions, onboarding, workflow generation) is
# metered for per-user COGS observability via ``ainvoke_structured`` but
# deliberately NOT charged to these windows — a memory save or an onboarding
# question must never consume the user's chat allowance. Memory volume is
# bounded by its own count cap (``FREE_MEMORY_FACT_LIMIT``), not by cost.
FREE_DAILY_COST_BUDGET_USD = 0.05  # TUNE
PRO_DAILY_COST_BUDGET_USD = 5.00  # TUNE — abuse guard, not a usage limit

# Rolling monthly USD cost budget for pro: the ECONOMIC guard. Set ~1x the
# subscription price so the worst-case whale is break-even. On exhaustion pro
# is NOT blocked — model routing degrades to the free-tier model for the rest
# of the month (see resolve_lane).
PRO_MONTHLY_COST_BUDGET_USD = 25.00  # TUNE

# TTLs for the budget Redis keys: sized just past their window so keys expire
# on their own (26h > 24h day, 32d > 31d month) even with clock skew.
DAILY_BUDGET_TTL_SECONDS = 26 * 60 * 60
MONTHLY_BUDGET_TTL_SECONDS = 32 * 24 * 60 * 60
# TTL for the per-request aggregate token counter (a single request never runs
# this long; the key just needs to outlive the longest legitimate run).
REQUEST_TOKEN_COUNTER_TTL_SECONDS = 30 * 60

# --- Tool-loop guardrails (LoopGuardMiddleware) ---------------------------------
# Escalating thresholds for a model stuck retrying a failing tool. "Identical"
# counts failures of the same tool with the same arguments; "same_tool" counts
# all failures of one tool this run regardless of arguments. At the WARN levels a
# nudge is appended in-band to the error; at the STOP levels (hard_stop runs only)
# the tool is no longer executed and a synthetic error is returned instead.
LOOP_GUARD_WARN_IDENTICAL = 2
LOOP_GUARD_WARN_SAME_TOOL = 3
LOOP_GUARD_STOP_IDENTICAL = 5
LOOP_GUARD_STOP_SAME_TOOL = 8
# The middleware is a per-process singleton, so failure counters are keyed by the
# run's thread_id and bounded to the most recent N runs (LRU) to keep memory flat.
LOOP_GUARD_MAX_TRACKED_RUNS = 512
