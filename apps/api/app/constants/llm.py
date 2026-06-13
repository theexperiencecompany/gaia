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
DEFAULT_GROK_MODEL_NAME = "x-ai/grok-4.1-fast"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
