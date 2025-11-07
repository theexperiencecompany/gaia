from typing import Any, Dict, List, Optional, TypedDict

from app.config.settings import settings
from app.constants.llm import (
    DEFAULT_GEMINI_MODEL_NAME,
    DEFAULT_MODEL_NAME,
)
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from langchain_core.language_models.chat_models import (
    BaseChatModel,
)
from langchain_core.runnables.utils import ConfigurableField
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

PROVIDER_MODELS = {
    "openai": DEFAULT_MODEL_NAME,
    "gemini": DEFAULT_GEMINI_MODEL_NAME,
}
PROVIDER_PRIORITY = {
    1: "openai",
    2: "gemini",
}


class LLMProvider(TypedDict):
    name: str
    instance: BaseChatModel


@lazy_provider(
    name="openai_llm",
    required_keys=[settings.OPENAI_API_KEY],
    strategy=MissingKeyStrategy.WARN,
    warning_message="OpenAI API key not configured. Models provided by openai will not work.",
)
def init_openai_llm():
    """Initialize OpenAI LLM with default model."""
    return ChatOpenAI(
        model=PROVIDER_MODELS["openai"],
        temperature=0.1,
        streaming=True,
        stream_usage=True,
    )


@lazy_provider(
    name="gemini_llm",
    required_keys=[settings.GOOGLE_API_KEY],
    strategy=MissingKeyStrategy.WARN,
    warning_message="Google API key not configured. Models provided by Google Gemini will not work.",
)
def init_gemini_llm():
    """Initialize Gemini LLM with default model."""
    return ChatGoogleGenerativeAI(
        model=PROVIDER_MODELS["gemini"],
        temperature=0.1,
    )


def init_llm(preferred_provider: Optional[str] = None, fallback_enabled: bool = True):
    """
    Initialize LLM with configurable alternatives based on provider priority.

    Args:
        preferred_provider (Optional[str]): Specific provider to prefer (e.g., "openai", "gemini").
                                          If None, uses default priority order.
        fallback_enabled (bool): Whether to enable fallback to other providers
                               if preferred provider is not available.

    Returns:
        Configured LLM instance with alternatives

    Raises:
        RuntimeError: If no LLM providers are properly configured
        ValueError: If preferred_provider is not a valid provider name
    """

    # Validate preferred provider if specified
    if preferred_provider and preferred_provider not in PROVIDER_MODELS:
        valid_providers = list(PROVIDER_MODELS.keys())
        raise ValueError(
            f"Invalid preferred_provider '{preferred_provider}'. "
            f"Valid providers are: {valid_providers}"
        )

    # Get available provider instances from global providers registry
    available_providers = _get_available_providers()

    if not available_providers:
        raise RuntimeError("No LLM providers are properly configured.")

    # Determine provider order based on preferred provider or default priority
    ordered_providers = _get_ordered_providers(
        available_providers, preferred_provider, fallback_enabled
    )

    if not ordered_providers:
        raise RuntimeError(
            f"Preferred provider '{preferred_provider}' is not available "
            f"and fallback is {'disabled' if not fallback_enabled else 'failed'}."
        )

    # Set up primary provider and alternatives
    primary_provider = ordered_providers[0]
    alternative_providers = ordered_providers[1:] if fallback_enabled else []

    return _create_configurable_llm(primary_provider, alternative_providers)


def _get_available_providers() -> Dict[str, Any]:
    """
    Retrieve available LLM provider instances from global providers registry.

    Returns:
        Dict mapping provider names to their instances
    """
    # Mapping of provider names to their instance keys in the providers registry
    provider_instance_mapping = {
        "openai": "openai_llm",
        "gemini": "gemini_llm",
    }

    available = {}
    for provider_name, instance_key in provider_instance_mapping.items():
        instance = providers.get(instance_key)
        if instance is not None:
            available[provider_name] = instance

    return available


def _get_ordered_providers(
    available_providers: Dict[str, Any],
    preferred_provider: Optional[str],
    fallback_enabled: bool,
) -> List[LLMProvider]:
    """
    Determine the order of providers based on preferences and availability.

    Args:
        available_providers: Dict of available provider instances
        preferred_provider: Specific provider name to prefer
        fallback_enabled: Whether to include fallback providers

    Returns:
        List of LLMProvider objects in priority order
    """
    ordered = []
    remaining_providers = available_providers.copy()

    # If a preferred provider is specified and available, prioritize it
    if preferred_provider and preferred_provider in available_providers:
        ordered.append(
            LLMProvider(
                name=preferred_provider,
                instance=available_providers[preferred_provider],
            )
        )
        # Remove from remaining providers to avoid duplicates
        remaining_providers.pop(preferred_provider)

    # Add remaining providers based on priority order (if fallback enabled or no preferred provider)
    if fallback_enabled or not ordered:
        for priority in sorted(PROVIDER_PRIORITY.keys()):
            provider_name = PROVIDER_PRIORITY[priority]
            if provider_name in remaining_providers:
                ordered.append(
                    LLMProvider(
                        name=provider_name, instance=remaining_providers[provider_name]
                    )
                )

    return ordered


def _create_configurable_llm(primary: LLMProvider, alternatives: List[LLMProvider]):
    """
    Create a configurable LLM instance with alternatives.

    Args:
        primary: Primary LLM provider to use
        alternatives: List of alternative providers for fallback

    Returns:
        Configured LLM instance with alternatives
    """
    if not alternatives:
        # Return primary instance directly if no alternatives
        return primary["instance"]

    # Create configurable alternatives mapping
    alternatives_mapping = {alt["name"]: alt["instance"] for alt in alternatives}

    primary_instance = primary["instance"]

    return primary_instance.configurable_alternatives(
        ConfigurableField(id="provider"),
        default_key=primary["name"],
        prefix_keys=False,
        **alternatives_mapping,
    )


def register_llm_providers():
    """Register LLM providers in the lazy loader."""
    init_openai_llm()
    init_gemini_llm()
