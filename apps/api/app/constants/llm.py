DEFAULT_LLM_PROVIDER = "gemini"
AGENT_RECURSION_LIMIT = 75  # Main agent graphs (comms, executor, provider subagents)
SUBAGENT_RECURSION_LIMIT = 25  # Spawned subagents (spawn_subagent tool loop)
DEFAULT_MAX_TOKENS = 1_000_000
DEFAULT_MODEL_NAME = "gemini-3.1-flash-lite-preview"
# Direct Gemini API model
DEFAULT_GEMINI_MODEL_NAME = "gemini-3.1-flash-lite-preview"
DEFAULT_GROK_MODEL_NAME = "x-ai/grok-4.1-fast"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Free/low-cost models via OpenRouter with automatic fallback
# Primary: Free experimental model (2.0 series - older but free)
# Fallbacks: Paid but cheap models
# Note: Version differs from DEFAULT_GEMINI_MODEL_NAME intentionally -
# free tier uses older 2.0 models while paid uses latest 2.5
DEFAULT_GEMINI_FREE_MODEL_NAME = "google/gemini-2.0-flash-exp:free"
GEMINI_FREE_FALLBACK_MODELS = [
    "google/gemini-2.0-flash-lite-001",
    "google/gemini-2.0-flash-001",
]
