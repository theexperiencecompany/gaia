from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal

from typing_extensions import TypedDict


class LLMProviderName(StrEnum):
    """Logical provider names, keying PROVIDER_MODELS and PROVIDER_PRIORITY.

    Also the value of the provider configurable that picks a lane per request.
    """

    GEMINI = "gemini"
    OPENROUTER = "openrouter"
    CUSTOM = "custom"


class LLMProviderKey(StrEnum):
    """Lazy-loader registry keys.

    Single source of truth for the @lazy_provider names and the lookup in
    _get_available_providers.
    """

    GEMINI = "gemini_llm"
    OPENROUTER = "openrouter_llm"
    CUSTOM = "custom_llm"


class ModelUse(StrEnum):
    """What a one-shot model call is for; resolve_model maps it to a provider, model and routing."""

    #: Every small auxiliary one-shot: titles, follow-ups, structured helpers, the browser writer.
    HELPER = "helper"
    #: The HIL approval judge, which runs on its own model (see HIL_JUDGE_MODEL_NAME).
    JUDGE = "judge"
    #: The memory pipeline's own provider (see MEMORY_MODEL_NAME).
    MEMORY = "memory"
    #: Every image -> text call (see VISION_MODEL_NAME).
    VISION = "vision"


class ReasoningLevel(StrEnum):
    """How much a one-shot call wants the model to think, independent of any provider's wire shape."""

    #: No reasoning at all.
    OFF = "off"
    #: The provider's cheapest non-zero effort.
    LIGHT = "light"


class DevLLMApi(StrEnum):
    """Which OpenAI-compatible API the custom dev endpoint (DEV_LLM_*) is called through."""

    CHAT_COMPLETIONS = "chat_completions"
    RESPONSES = "responses"


#: OpenRouter's reasoning efforts, the values its request's reasoning.effort accepts.
OpenRouterEffort = Literal["xhigh", "high", "medium", "low", "minimal", "none"]


class OpenRouterReasoning(TypedDict):
    """OpenRouter's reasoning request object, as GAIA sends it: an effort and nothing else.

    ChatOpenRouter declares its reasoning field dict[str, Any]; this is the part
    of that free-form object GAIA writes.
    """

    effort: OpenRouterEffort


class OpenRouterProviderRouting(TypedDict, total=False):
    """OpenRouter's provider-routing block: a soft order, or a hard only-these pin.

    total=False because the two uses set different keys: the client's
    OPENROUTER_PROVIDER_ORDER writes order + allow_fallbacks, a dev-menu pin
    writes only.
    """

    order: list[str]
    only: list[str]
    allow_fallbacks: bool


class OpenRouterModelKwargs(TypedDict):
    """The model_kwargs payload carrying a provider-routing block."""

    provider: OpenRouterProviderRouting


@dataclass(frozen=True, slots=True)
class DevModelOption:
    """One entry of the DEV-ONLY model menu (DEV_MODEL_OPTIONS below).

    A frozen dataclass: a fixed in-process record, read by attribute, that
    crosses no validation boundary.
    """

    #: Keyed like PROVIDER_MODELS and PROVIDER_PRIORITY; the enum stops the menu
    #: naming a lane the client cannot resolve.
    provider: LLMProviderName
    #: None = pin no model; the client's own default serves the request.
    model: str | None
    #: The OpenRouter provider-routing pin the lane carries as model_kwargs.
    provider_pin: OpenRouterModelKwargs | None
    reasoning: bool


class LaneConfig(TypedDict):
    """A ModelLane's JSON-safe form, stored on configurable[LANE_FIELD_ID].

    Here, not beside ModelLane, so AgentConfigurable (a leaf module) can
    declare the key without importing the LLM client.
    """

    provider: LLMProviderName
    model: str | None
    reasoning: OpenRouterReasoning | None
    provider_pin: OpenRouterModelKwargs | None
    max_input_tokens: int


# LangChain's field-resolution keys, written at TWO definition sites (Gemini's
# ConfigurableField and OpenRouter's) and produced at a third (ModelLane.binding_keys);
# nothing enforced they agreed, which is how the Gemini/OpenRouter model ids got SWAPPED.
MODEL_FIELD_ID = "model"
PROVIDER_FIELD_ID = "provider"
REASONING_FIELD_ID = "reasoning"
MODEL_KWARGS_FIELD_ID = "model_kwargs"

# The configurable key the whole resolved ModelLane rides under.
LANE_FIELD_ID = "lane"

GEMINI_PROVIDER = "gemini"
OPENROUTER_PROVIDER = "openrouter"

DEFAULT_LLM_PROVIDER = OPENROUTER_PROVIDER

# The response_metadata key for the upstream that actually served an OpenRouter
# call ("Baidu", "StreamLake", ...), unlike model_provider (LangChain-owned,
# stamped with the aggregator's own name). Set by openrouter_provider_name_patch.
PROVIDER_NAME_METADATA_KEY = "provider_name"

# How often DeltaChannel writes a full snapshot (every Nth update); between
# snapshots only deltas persist, so storage grows ~O(N) instead of O(N²). Lower =
# more storage but faster reconstruction; higher = less storage, deeper replay.
MESSAGES_SNAPSHOT_FREQUENCY = 50

# Runaway loops are the main driver of long, expensive traces; capping tail
# risk keeps p95 cost predictable. Legitimate tasks that need more steps
# should split work across spawns rather than chew through recursion budget.
AGENT_RECURSION_LIMIT = 40  # Comms + workers (routing / focused work)
# The executor runs long multi-step tool loops across several integrations, so 40
# truncates real work with GraphRecursionError. Both the graph runtime limit and
# the accounting middleware's denominator read this, so they stay in sync.
EXECUTOR_RECURSION_LIMIT = 100
SUBAGENT_RECURSION_LIMIT = 15  # Spawned subagents (spawn_subagent tool loop)
# The workflow authoring subagent only discovers integrations/triggers then emits
# JSON, never executes, so a handful of discovery calls is plenty. On hitting the
# limit the runner forces a final answer instead of crashing ("stop wandering").
WORKFLOW_SUBAGENT_RECURSION_LIMIT = 20
# Emit a ``recursion_high_water_mark`` wide event when a run uses ≥80% of
# its limit so we can tune the cap from real traffic.
RECURSION_HWM_FRACTION = 0.80
# When this few supersteps remain before the limit, acall_model injects a
# wrap-up notice so the model finishes with a summary instead of GraphRecursionError.
RECURSION_WRAPUP_THRESHOLD_STEPS = 6

# Nudges the executor on unconfirmed work (a pending tracked todo, or no real
# tool ran). Scoped to the CURRENT delegation — counting the executor thread
# instead let each delegation inherit the previous one's nudges.
MAX_COMPLETION_NUDGES = 1
# Tool results that prove no work happened: discovery-only or failed calls.
COMPLETION_NON_WORK_TOOLS = frozenset({"retrieve_tools"})
COMPLETION_NUDGE_MESSAGE = (
    "[System: before you finish, every part of the task must actually be done "
    "and confirmed with tools, not assumed. If anything is still pending, not yet "
    "verified, or an action you described but did not take, do it now. Nothing "
    "runs after your reply ends, so never tell the user you are still working or "
    "that more results are coming ('hang tight', 'still digging'): either do the "
    "work now with tools, or state plainly what you got and what failed. If you "
    "are genuinely finished, reply with your complete final result.]"
)
# A plain-text stop that PROMISES future work is never valid: the run is over the
# moment the reply ends, so "hang tight" is a lie. Lowercase substrings matched
# against the final reply; each entry must be an unambiguous forward commitment.
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

# Per-tool-call timeout: a hung integration call previously hung the entire run
# forever (no timeout existed at any dispatch layer). Orchestration tools that
# legitimately run for minutes are exempt — they own their lifecycle management.
TOOL_EXECUTION_TIMEOUT_SECONDS = 120
TOOL_TIMEOUT_EXEMPT_TOOLS = frozenset(
    {
        "call_executor",
        "cancel_executor",
        "spawn_subagent",
        "handoff",
        "deep_research",
        "browser_task",
        # bash carries its own deadline down (the e2b server-side command timeout,
        # capped at BASH_MAX_TIMEOUT_SECONDS); bounding it here capped every command
        # at 120s while the tool advertised 300 and killed code-mode execute() calls.
        "bash",
    }
)
# How much longer the tool node waits than the bound closer to the tool: it must
# expire strictly after dispatch_tool's inner bound, else the outer deadline wins
# and the model only ever sees the node's generic timeout text.
TOOL_TIMEOUT_BACKSTOP_BUFFER_SECONDS = 15

# Run-metadata key carrying each call's label so TTFT callbacks can attribute a
# sample: one turn's callback list is shared by the comms call and its title,
# follow-up and memory side calls, which the run-level agent name cannot separate.
LLM_LABEL_METADATA_KEY: Final = "llm_label"

# Attempts for the model-level transient-error retry before the caller falls back
# to the default model (see with_llm_retry in app/agents/llm/client.py).
LLM_RETRY_MAX_ATTEMPTS = 3

# Sticky routing (the session_id hint pinning a chain to one upstream) is
# OpenRouter-only wire behaviour: Gemini rejects the key, and CUSTOM runs
# ChatOpenAI where session_id is unsupported on AsyncCompletions.create.
STICKY_ROUTING_PROVIDERS = frozenset({LLMProviderName.OPENROUTER})
# Auxiliary one-shots route on their own sticky session: sharing the
# conversation's key re-pinned its provider from a background call (measured).
AUX_SESSION_SUFFIX = "-aux"

# Total wall-clock ceiling for one ainvoke_llm call, backstopping a provider that accepts
# the connection and never answers. Sized for the slowest legitimate caller, not a per-caller
# budget: pass a tighter value on a user-blocking path, or timeout=None to opt out entirely.
LLM_INVOKE_TIMEOUT_SECONDS = 300

# Near-deterministic default for every LLM call; creative tasks opt into more
# variation via resolve_model(temperature=...).
DEFAULT_LLM_TEMPERATURE = 0.1

# Context window of the default model, in input tokens; update whenever
# DEFAULT_MODEL_NAME changes. Middleware built at graph-build time keeps
# fractional triggers denominated in THIS window even under a different model.
DEFAULT_MAX_TOKENS = 1_000_000
# Changing the default model is high blast radius: update DEFAULT_MAX_TOKENS
# (else fractional-token middleware fails to build) and add a MODEL_PRICING entry.
# Text-only default for every tier: image tool results are captioned, not shown.
DEFAULT_MODEL_NAME = "deepseek/deepseek-v4-flash-0731"
# The HIL intent judge runs here, not AUX_MODEL_NAME: accuracy and tail latency
# beat sharing the graph lane's cache. The eval (50 scenarios, real LLMs) put
# this at 42/50 in 1.9s p95 vs the default's 40/50 in 20s p95. Changing re-runs it.
HIL_JUDGE_MODEL_NAME = "google/gemini-3.5-flash-lite"
# OpenRouter `models`-array fallback for the judge only: tried in order on
# rate limits, downtime, and moderation refusals — never on verdicts. The
# fallback's bias is fail-safe (it over-asks rather than over-approves).
HIL_JUDGE_FALLBACK_MODEL_NAMES: tuple[str, ...] = ("deepseek/deepseek-v4-flash-0731",)
# Stand-in when a call reports no model id. Priced at DEFAULT_PRICING rather
# than its real rate, so its appearance is an alertable bug, not a benign
# default — both metering routes log it loudly.
UNKNOWN_MODEL_NAME = "unknown"
# No explicit routing: OpenRouter's default + session_id sticky measured BEST
# (82.2%) vs. a first-party `only` pin (64-66%). Same id as the graph on its own
# sticky sessions ("-aux") — a separate model id here couldn't cache TOOL requests.
AUX_MODEL_NAME = DEFAULT_MODEL_NAME

# The OpenRouter chat models GAIA runs, mapped to whether images survive in their
# TOOL results (vetted live by tests/model_onboarding). Add a model here (with its
# MODEL_PRICING entry) and nowhere else; False routes tool media through the caption fallback.
OPENROUTER_MODEL_TOOL_IMAGE_SUPPORT: dict[str, bool] = {
    DEFAULT_MODEL_NAME: False,
}
# Retained for the direct-Gemini lane, which is still selectable as a provider
# alternative and in the dev model menu — it is no longer the default.
DEFAULT_GEMINI_MODEL_NAME = "gemini-3.1-flash-lite"

# The model behind every memory-pipeline call. Deliberately a DIFFERENT provider:
# concurrent same-provider requests wipe each other's cached chains mid-read
# (measured: comms chain collapses to ~0 vs. ~99.5% held with Gemini).
MEMORY_MODEL_NAME = DEFAULT_GEMINI_MODEL_NAME
DEFAULT_GROK_MODEL_NAME = "x-ai/grok-4.3"

# The model behind every image -> text call. Deliberately NOT tied to
# DEFAULT_MODEL_NAME (may be text-only): a blind describer fails SILENTLY
# (describe_image degrades to None with nothing in the logs).
VISION_MODEL_PROVIDER = GEMINI_PROVIDER
VISION_MODEL_NAME = DEFAULT_GEMINI_MODEL_NAME

# GAIA_SIM_MODE (see app/agents/llm/client.py): every model factory resolves to
# the local scripted stub (tools/llm-stub) at this address. The model name is a
# marker the stub ignores; the key satisfies client construction only.
SIM_STUB_BASE_URL = "http://localhost:9797/api/v1"
SIM_STUB_API_KEY = "sk-stub-dev"  # pragma: allowlist secret
SIM_STUB_MODEL_NAME = "gaia-sim-stub"

# Per-plan model policy (hardcoded; not user-selectable). Both tiers run the SAME
# model today, so the pro monthly-budget degrade in resolve_lane has nothing to
# degrade to — kept so re-pointing PAID_MODEL_NAME makes that guard bite again.
PAID_MODEL_PROVIDER = OPENROUTER_PROVIDER
PAID_MODEL_NAME = DEFAULT_MODEL_NAME

# Which OpenRouter models accept image input, straight from the live catalog's
# architecture.input_modalities — vision support needs no per-model curation
# here (see app/agents/llm/model_catalog.py for the cache).
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_MODEL_CATALOG_TTL_SECONDS = 3600
OPENROUTER_MODEL_CATALOG_TIMEOUT_SECONDS = 10
# How long a failed catalog refresh is remembered: the catalog is consulted on
# the pre-model hook, so without a backoff an OpenRouter outage would cost every
# model call a full fetch timeout.
OPENROUTER_MODEL_CATALOG_RETRY_SECONDS = 300

# GLM 5.2's first-party (z-ai) lane exposes a 1M-token window and a 131k output
# ceiling; capping at 64k leaves ample headroom given compaction at 0.40 and
# summary at 0.60 of the window.
OPENROUTER_MAX_OUTPUT_TOKENS = 64_000

# Output cap for one-shot helper calls. OpenRouter reserves credit against
# max_tokens per call, so a 200-token title 402'd against the full 64k
# reservation; 8k is ~10x the largest observed helper output.
HELPER_MAX_OUTPUT_TOKENS = 8_000

# Default reasoning effort for OpenRouter thinking models (executor + subagents),
# passed to ChatOpenRouter's native `reasoning` field.
OPENROUTER_REASONING: OpenRouterReasoning = {"effort": "medium"}
# Its own constant so raising it doesn't move the executor's default. It sat at
# "low" while free comms inherited "medium" — a paying user's agent thought LESS
# than a free user's; paid comms must never be thinner than free.
PAID_COMMS_REASONING: OpenRouterReasoning = {"effort": "medium"}


# OFF is "none": deepseek-v4-flash reasoned at "minimal" and "low", and at
# enabled=False too (111-167 tokens on a short prompt, its 8000 cap on a part
# judgement); "none" measured 0. tests/model_onboarding/test_reasoning_off.py.
OPENROUTER_REASONING_EFFORT: Final[dict[ReasoningLevel, Literal["none", "minimal"]]] = {
    ReasoningLevel.OFF: "none",
    ReasoningLevel.LIGHT: "minimal",
}
# OpenAI's own efforts, for the reasoning_effort (chat completions) and
# reasoning.effort (Responses) fields. LIGHT is "low": gpt-6-luna rejects
# "minimal" on both APIs, and every OpenAI reasoning model accepts "low".
OPENAI_REASONING_EFFORT: Final[dict[ReasoningLevel, Literal["none", "low"]]] = {
    ReasoningLevel.OFF: "none",
    ReasoningLevel.LIGHT: "low",
}
# A custom-lane call that names no level: gpt-6-luna's own default is "medium",
# which took memory extraction from a 15 s median to 50 s and a chat turn from 5 s to 31 s.
DEV_LLM_DEFAULT_REASONING: Final = ReasoningLevel.LIGHT

# Output cap for the env-defined custom dev provider, well under the model's
# 65,536 ceiling: these cheap lanes RESERVE max_tokens per request, so a 64k cap
# 402'd as soon as balance dipped, while a 256-token probe still succeeded.
DEV_LLM_MAX_OUTPUT_TOKENS = 16_000

# Longest silence one custom-lane reply may keep: the SDK default (600 s) let one
# stalled gpt-6-luna reply eat LLM_INVOKE_TIMEOUT_SECONDS. Every retry attempt fits
# in that budget; a healthy high-effort reply's longest measured gap was 24 s.
DEV_LLM_READ_TIMEOUT_SECONDS = 90
DEV_LLM_CONNECT_TIMEOUT_SECONDS = 10

# Discounted DEV_LLM_* lanes sit behind Cloudflare, which 403s (error 1010)
# programmatic user agents; a browser UA sent as a default header passes.
DEV_LLM_BROWSER_HEADERS: Final[dict[str, str]] = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
}

# OpenRouter app attribution, sent as HTTP-Referer/X-Title/X-OpenRouter-Categories.
# Development sends a fixed synthetic referer since a localhost FRONTEND_URL
# lands in the dashboard's "unknown app" bucket.
OPENROUTER_APP_TITLE = "GAIA"
OPENROUTER_DEV_APP_URL = "https://dev.heygaia.io"
OPENROUTER_DEV_APP_TITLE = "GAIA (dev)"
OPENROUTER_APP_CATEGORIES = ["personal-agent", "general-chat"]

# The dev menu key of the env-defined custom endpoint. DEV_DEFAULT_MODEL set to
# it, in development, sends every LLM call there (see app/agents/llm/dev_lane.py).
DEV_CUSTOM_MODEL_OPTION = "custom"

# DEV-ONLY model menu: the dev chat-header selector sends a stable id per role
# and the backend pins the matching model. Gemini models route direct and ignore
# model_kwargs/reasoning. Never used in production.
DEV_MODEL_OPTIONS: dict[str, DevModelOption] = {
    "minimax-m3": DevModelOption(
        provider=LLMProviderName.OPENROUTER,
        model="minimax/minimax-m3",
        provider_pin={"provider": {"only": ["minimax"]}},
        reasoning=True,
    ),
    "glm-5.2": DevModelOption(
        provider=LLMProviderName.OPENROUTER,
        model="z-ai/glm-5.2",
        provider_pin={"provider": {"only": ["z-ai"]}},
        reasoning=True,
    ),
    "gemini-3.5-flash": DevModelOption(
        provider=LLMProviderName.OPENROUTER,
        model="google/gemini-3.5-flash",
        provider_pin=None,
        reasoning=False,
    ),
    "deepseek-v4": DevModelOption(
        provider=LLMProviderName.OPENROUTER,
        model="deepseek/deepseek-v4-pro",
        provider_pin=None,
        reasoning=False,
    ),
    "deepseek-v4-flash": DevModelOption(
        # Pinned snapshot — same id also served by the cheap OpenRouter-compatible
        # lanes (e.g. Nous Research), so the custom endpoint below can run the
        # identical model for A/B-ing routes.
        provider=LLMProviderName.OPENROUTER,
        model="deepseek/deepseek-v4-flash-0731",
        # Deliberately unpinned — the pin measured worse on the real graph
        # (see the paid-lane rationale above).
        provider_pin=None,
        reasoning=False,
    ),
    DEV_CUSTOM_MODEL_OPTION: DevModelOption(
        # The env-defined endpoint (DEV_LLM_* settings). `model` None = don't pin
        # one here; the client's own default (DEV_LLM_MODEL) serves the request.
        provider=LLMProviderName.CUSTOM,
        model=None,
        provider_pin=None,
        reasoning=False,
    ),
    "gemini-3.1-flash-lite": DevModelOption(
        provider=LLMProviderName.GEMINI,
        model="gemini-3.1-flash-lite",
        provider_pin=None,
        reasoning=False,
    ),
}

# --- Tier cost enforcement (free = usage walls, pro = abuse guards) --------------
# Hard ceiling on TOTAL tokens (comms + executor + every subagent) before the
# accounting middleware stops a request; pro is set high enough that only a runaway loop trips it.
FREE_PER_REQUEST_TOKEN_CEILING = 300_000  # TUNE
PRO_PER_REQUEST_TOKEN_CEILING = 5_000_000  # TUNE

# Rolling daily USD cost budget. Free: reaching it blocks ALL chat until reset.
# Pro: an abuse-level burst guard only. Auxiliary background spend (memory,
# onboarding, workflow generation) is metered separately and never charged here.
FREE_DAILY_COST_BUDGET_USD = 0.05  # TUNE
PRO_DAILY_COST_BUDGET_USD = 5.00  # TUNE — abuse guard, not a usage limit

# When remaining daily budget headroom drops to this fraction (0.2 = 80% spent),
# the accounting middleware injects a one-time wrap-up notice, before
# is_daily_budget_exhausted kills the run mid-flight with no answer.
BUDGET_WRAPUP_REMAINING_FRACTION = 0.2

# Rolling monthly USD cost budget for pro: the ECONOMIC guard, ~1x the
# subscription price. On exhaustion pro is NOT blocked — routing degrades to
# the free-tier model for the rest of the month.
PRO_MONTHLY_COST_BUDGET_USD = 25.00  # TUNE

# TTLs for the budget Redis keys: sized just past their window so keys expire
# on their own (26h > 24h day, 32d > 31d month) even with clock skew.
DAILY_BUDGET_TTL_SECONDS = 26 * 60 * 60
MONTHLY_BUDGET_TTL_SECONDS = 32 * 24 * 60 * 60
# TTL for the per-request aggregate token counter (a single request never runs
# this long; the key just needs to outlive the longest legitimate run).
REQUEST_TOKEN_COUNTER_TTL_SECONDS = 30 * 60

# --- Tool-loop guardrails (LoopGuardMiddleware) ---------------------------------
# "Identical" = same tool+args; "same_tool" = any failure of that tool. WARN appends an
# in-band nudge to the error ToolMessage; STOP skips the call, returning a synthetic error.
LOOP_GUARD_WARN_IDENTICAL = 2
LOOP_GUARD_WARN_SAME_TOOL = 3
LOOP_GUARD_STOP_IDENTICAL = 5
LOOP_GUARD_STOP_SAME_TOOL = 8
# "Repeat" counts CONSECUTIVE identical calls regardless of success or failure:
# a successful call whose result won't change is as much a loop as a failing
# one (the failure counters above only see status="error").
LOOP_GUARD_WARN_REPEAT = 3
LOOP_GUARD_STOP_REPEAT = 6
# The middleware is a per-process singleton, so failure counters are keyed by the
# run's thread_id and bounded to the most recent N runs (LRU) to keep memory flat.
LOOP_GUARD_MAX_TRACKED_RUNS = 512
