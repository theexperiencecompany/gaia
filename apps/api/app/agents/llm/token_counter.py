from app.core.lazy_loader import providers


def get_token_counter(provider: str | None = None):
    """Get the token counter based on provider and model name."""
    if provider == "openai":
        return providers.get("openai_llm")
    if provider == "gemini":
        return providers.get("gemini_llm")

    return providers.get("openai_llm")
