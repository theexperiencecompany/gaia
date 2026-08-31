from typing import Any

from app.agents.llm.types import DevModelOption, LLMProviderName

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

# The ``response_metadata`` key carrying the name of the upstream that actually
# served an OpenRouter call ("Baidu", "StreamLake", ...), as opposed to
# ``model_provider``, which LangChain owns and which OpenRouter's integration
# stamps with the aggregator's own name. Set by
# ``openrouter_provider_name_patch`` and read by anything attributing a call to
# the vendor that served it.
PROVIDER_NAME_METADATA_KEY = "provider_name"

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

# Harness-owned completion: when the executor tries to end with a plain-text
# message while work is demonstrably unfinished, the loop injects up to this many
# "verify or continue" nudges instead of ending. "Unfinished" means a tracked todo
# is still pending, or no real tool ran on the delegated task (discovery calls
# like retrieve_tools and errored calls don't count). A raw count floor sat here
# once and told one-call tasks ("send the email") the work may not have
# happened, goading a duplicate send. Both counts are scoped to the CURRENT delegation
# (middleware.completion.current_delegation), not the executor thread, which
# outlives it: counting the thread let each delegation inherit the previous one's
# tools and nudges, so the guard fired once per conversation and never again.
# Bounded so a genuinely quick task costs at most this many extra steps per
# delegation. Only the executor opts in (require_finish_to_end); comms may always
# end in plain text.
MAX_COMPLETION_NUDGES = 1
# Tool results that prove no work happened: discovery-only or failed calls.
COMPLETION_NON_WORK_TOOLS = frozenset({"retrieve_tools"})
COMPLETION_NUDGE_MESSAGE = (
    "[System: before you finish — every part of the task must actually be done "
    "and confirmed with tools, not assumed. If anything is still pending, not yet "
    "verified, or an action you described but did not take, do it now. Nothing "
    "runs after your reply ends, so never tell the user you are still working or "
    "that more results are coming ('hang tight', 'still digging'): either do the "
    "work now with tools, or state plainly what you got and what failed. If you "
    "are genuinely finished, reply with your complete final result.]"
)
# A plain-text stop that PROMISES future work is never a valid ending: the run
# is over the moment the reply ends, so "hang tight" is a lie to the user.
# Lowercase substrings, matched against the final reply. Kept deliberately
# specific — a false positive only costs one bounded nudge, but each entry
# should still be an unambiguous forward commitment.
COMPLETION_PROMISE_MARKERS: tuple[str, ...] = (
    "hang tight",
    "still digging",
    "still working on",
    "still fetching",
    "still searching",
    "still looking",
    "keep digging",
    "keep looking",
    "give me a moment",
    "give me a sec",
    "one moment while",
    "bear with me",
    "stay tuned",
    "i'll get back to you",
    "will get back to you",
    "i'll keep you posted",
    "keep you posted",
    "i'll follow up",
    "will follow up shortly",
    "check back soon",
    "coming right up",
    "working on it now",
    "in the background",
)

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

# Sticky routing (the ``session_id`` hint that pins a chain to one upstream) is
# OpenRouter-wire behaviour. Gemini has no sticky routing, so the key is an
# unsupported argument there and must never be sent.
STICKY_ROUTING_PROVIDERS = frozenset({LLMProviderName.OPENROUTER, LLMProviderName.CUSTOM})
# Auxiliary one-shots route on their own sticky session: sharing the
# conversation's key re-pinned its provider from a background call (measured).
AUX_SESSION_SUFFIX = "-aux"

# Total wall-clock ceiling for one ainvoke_llm call — retries, backoff sleeps and the
# fallback attempt included. A backstop against a provider that accepts the connection
# and then never answers, which no retry can rescue because nothing ever raises.
#
# Sized for the slowest legitimate caller (onboarding intelligence, workflow generation,
# document analysis), NOT as a per-caller latency budget: a call on a user-blocking path
# should pass its own tighter value, the way the HIL gate passes
# HIL_LLM_TIMEOUT_SECONDS. Pass timeout=None to opt out entirely.
LLM_INVOKE_TIMEOUT_SECONDS = 300

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
#   - pricing entry    -> MODEL_PRICING in app/config/model_pricing.py; without
#     one, calculate_token_cost falls back to DEFAULT_PRICING and the cost
#     budgets meter at the wrong rate (the pricing unit test enforces this)
#   - it's multimodal if vision/file tools rely on it
# Default model for every tier and every auxiliary call, served over OpenRouter.
# Text-only: tool results carrying images are captioned for it rather than shown
# (see agents/llm/vision/capability.py).
DEFAULT_MODEL_NAME = "deepseek/deepseek-v4-flash-0731"
# Stand-in when a call reports no model id. Priced at DEFAULT_PRICING rather
# than its real rate, so its appearance is an alertable bug, not a benign
# default — both metering routes log it loudly.
UNKNOWN_MODEL_NAME = "unknown"
# No explicit provider routing for the default DeepSeek lane: OpenRouter's
# default (price- and availability-weighted) routing + the session_id sticky
# key on every request measured BEST on the real full graph (82.2% total,
# 83-88% steady-state). The first-party `only` pin was measured WORSE on the
# real graph (64-66%: the pinned upstream's cache state is colder and the
# conversation's segments still intermittently fail to join), even though it
# is rock-stable in isolation — the isolation is not the graph.
# A separate id for the auxiliary one-shot calls (memory pipeline, follow-ups,
# vision, …). This is NOT the same model as the default: OpenRouter serves the
# bare id as the ORIGINAL V4 Flash release ("0423", created Apr 2026), while
# DEFAULT_MODEL_NAME is the re-post-trained "0731" revision (Aug 2026) — same
# architecture family (284B/13B-active MoE, 1M context), different model
# version — and NOT the same rate card. Aux one-shots (follow-up suggestions, conversation
# naming) are therefore served by the older revision — a deliberate tradeoff:
# the separate model id is what gives these calls their own provider-side
# cache namespace. They must NOT share the conversation's namespace — their
# ~30k tokens/turn of new blocks were evicting the conversation chain between
# turns (measured: real-graph hit rate capped at ~63% while the intra-turn
# steady state is 87–91%).
#
# That isolation used to come from a SEPARATE model id (the original V4 Flash).
# It now comes from the suffixed sticky sessions ("-aux", "memory-{user}"),
# because the separate id's provider pool turned out unable to cache or hold
# affinity for TOOL-carrying requests at all — measured with fixed sessions:
# the old id read [1536,0]/[0,0]/[0,0] across three sessions while this id
# read [0,1792,1792]/[1792,1792,1792], and every structured one-shot carries a
# tool. Same id as the graph, different sessions: the chains stay separate per
# key, and the follow-up/memory lanes get a pool that actually caches them.
AUX_MODEL_NAME = DEFAULT_MODEL_NAME

# The OpenRouter-served chat models GAIA runs, mapped to whether images survive
# in their TOOL results (the onboarding gate in tests/model_onboarding vets the
# flag with a live call — see its module docstring for why no listing can answer
# this). This is the single declaration the gate parameterises off, so a model
# is added here (with its MODEL_PRICING entry in app/config/model_pricing.py)
# and nowhere else. False routes tool media through the caption fallback
# (agents/llm/vision/) instead of asserting the model sees pixels.
OPENROUTER_MODEL_TOOL_IMAGE_SUPPORT: dict[str, bool] = {
    DEFAULT_MODEL_NAME: False,
}
# Retained for the direct-Gemini lane, which is still selectable as a provider
# alternative and in the dev model menu — it is no longer the default.
DEFAULT_GEMINI_MODEL_NAME = "gemini-3.1-flash-lite"

# The model behind every memory-pipeline call (extraction / categorization /
# reconciliation / consolidation). Deliberately a DIFFERENT provider than the
# graph's lane: the memory extraction is a background task that overlaps the
# next turn's requests, and concurrent requests on the same provider's cache
# store wipe each other's cached chains mid-read (measured: the comms chain
# collapses to ~0 under a concurrent same-provider extraction and holds
# ~99.5% under a concurrent Gemini extraction). A different provider has no
# shared cache store, so the overlap is harmless.
MEMORY_MODEL_NAME = DEFAULT_GEMINI_MODEL_NAME
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

# Output cap for one-shot helper calls (conversation naming, memory extraction,
# structured JSON blobs, onboarding copy, moderation, category inference) — every
# get_default_llm() consumer EXCEPT the agent-graph fallback and the
# summarization/compaction middleware, which legitimately produce long output and
# keep OPENROUTER_MAX_OUTPUT_TOKENS. OpenRouter reserves credit against `max_tokens`
# per call, so a helper emitting a 200-token title was demanding the full 64k
# reservation and 402ing on a low balance even though it had credit for its real
# (tiny) output. 8k is ~10x the largest observed helper output while cutting the
# reservation 8x.
HELPER_MAX_OUTPUT_TOKENS = 8_000

# Default reasoning effort for OpenRouter thinking models (executor + subagents),
# passed to ChatOpenRouter's native `reasoning` field.
OPENROUTER_REASONING: dict[str, Any] = {"effort": "medium"}
# Reasoning effort for a PAID comms turn. Its own constant rather than a reuse of
# OPENROUTER_REASONING because it is the knob that raises paid comms further
# (GLM 5.2 also documents "high"/"xhigh"); the executor's default must not move
# with it. It sat at "low" while free comms inherited "medium" from the client
# default, so a paying user's front-door agent thought LESS than a free user's.
# Floor: paid comms is never thinner than free comms.
PAID_COMMS_REASONING: dict[str, Any] = {"effort": "medium"}

# Output cap for the env-defined custom dev provider (the "custom" entry below;
# endpoint/key/model all come from the DEV_LLM_* settings). 64k fits under the
# completion ceilings of the cheap lanes this is meant for (e.g. DeepSeek V4
# Flash caps at 65,536).
DEV_LLM_MAX_OUTPUT_TOKENS = 64_000

# OpenRouter app attribution (https://openrouter.ai/docs/app-attribution). The
# OpenRouter client surfaces these as the HTTP-Referer / X-Title /
# X-OpenRouter-Categories headers so GAIA appears on OpenRouter's app rankings.
# In production the referer is the public site (settings.FRONTEND_URL);
# development sends a fixed synthetic referer instead, because a localhost
# FRONTEND_URL cannot be attributed and the traffic lands in the dashboard's
# "unknown app" bucket — indistinguishable from a misconfigured caller.
OPENROUTER_APP_TITLE = "GAIA"
OPENROUTER_DEV_APP_URL = "https://dev.heygaia.io"
OPENROUTER_DEV_APP_TITLE = "GAIA (dev)"
OPENROUTER_APP_CATEGORIES = ["personal-agent", "general-chat"]

# DEV-ONLY model menu (ENV=development). The dev chat-header selector sends one of
# these stable ids per role (comms / executor); the backend pins the matching model.
# `reasoning` flags whether the model is an OpenRouter reasoning model — effort is
# applied per-role at override time (comms -> PAID_COMMS_REASONING, executor ->
# OPENROUTER_REASONING). Gemini models route direct via the "gemini" provider and
# ignore OpenRouter `model_kwargs`/`reasoning`. This menu is NEVER used in production.
DEV_MODEL_OPTIONS: dict[str, DevModelOption] = {
    "minimax-m3": {
        "provider": LLMProviderName.OPENROUTER,
        "model": "minimax/minimax-m3",
        "model_kwargs": {"provider": {"only": ["minimax"]}},
        "reasoning": True,
    },
    "glm-5.2": {
        "provider": LLMProviderName.OPENROUTER,
        "model": "z-ai/glm-5.2",
        "model_kwargs": {"provider": {"only": ["z-ai"]}},
        "reasoning": True,
    },
    "gemini-3.5-flash": {
        "provider": LLMProviderName.OPENROUTER,
        "model": "google/gemini-3.5-flash",
        "model_kwargs": None,
        "reasoning": False,
    },
    "deepseek-v4": {
        "provider": LLMProviderName.OPENROUTER,
        "model": "deepseek/deepseek-v4-pro",
        "model_kwargs": None,
        "reasoning": False,
    },
    "deepseek-v4-flash": {
        # Pinned snapshot — same id also served by the cheap OpenRouter-compatible
        # lanes (e.g. Nous Research), so the custom endpoint below can run the
        # identical model for A/B-ing routes.
        "provider": LLMProviderName.OPENROUTER,
        "model": "deepseek/deepseek-v4-flash-0731",
        # Deliberately unpinned — the pin measured worse on the real graph
        # (see the paid-lane rationale above).
        "model_kwargs": None,
        "reasoning": False,
    },
    "custom": {
        # The env-defined endpoint (DEV_LLM_* settings). `model` None = don't pin
        # one here; the client's own default (DEV_LLM_MODEL) serves the request.
        "provider": LLMProviderName.CUSTOM,
        "model": None,
        "model_kwargs": None,
        "reasoning": False,
    },
    "gemini-3.1-flash-lite": {
        "provider": LLMProviderName.GEMINI,
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

# When remaining daily budget headroom drops to this fraction of the full budget
# (0.2 = 20% left, i.e. 80% spent), the accounting middleware injects a one-time
# wrap-up notice telling the agent to stop gathering and answer with what it has —
# before is_daily_budget_exhausted binds and kills the run mid-flight with no answer.
BUDGET_WRAPUP_REMAINING_FRACTION = 0.2

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
# "Repeat" counts CONSECUTIVE identical calls (same tool + same args) regardless
# of success or failure — the signature of a redundant duplicate handoff or a
# wasteful re-run of the exact same search. A successful call whose result won't
# change is as much a loop as a failing one; the failure counters above only see
# status="error". Warn appends an in-band note; stop (hard_stop runs only) blocks
# the redundant call before it executes.
LOOP_GUARD_WARN_REPEAT = 3
LOOP_GUARD_STOP_REPEAT = 6
# The middleware is a per-process singleton, so failure counters are keyed by the
# run's thread_id and bounded to the most recent N runs (LRU) to keep memory flat.
LOOP_GUARD_MAX_TRACKED_RUNS = 512
