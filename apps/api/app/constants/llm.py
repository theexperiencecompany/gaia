DEFAULT_LLM_PROVIDER = "openai"
DEFAULT_MAX_TOKENS = 24000
DEFAULT_OPENAI_MODEL_NAME = "gpt-4o-mini"
DEFAULT_MODEL_NAME = DEFAULT_OPENAI_MODEL_NAME
DEFAULT_GEMINI_MODEL_NAME = "gemini-2.5-flash"
DEFAULT_GROK_MODEL_NAME = "x-ai/grok-4.1-fast"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Free/low-cost models via OpenRouter with automatic fallback
# Primary: Free experimental model, Fallbacks: Paid but cheap models
DEFAULT_GEMINI_FREE_MODEL_NAME = "google/gemini-2.0-flash-exp:free"
GEMINI_FREE_FALLBACK_MODELS = [
    "google/gemini-2.0-flash-lite-001",
    "google/gemini-2.0-flash-001",
]
