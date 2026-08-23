from enum import Enum
from typing import Any, TypedDict

from app.agents.llm.types import LLMProviderName


class ModelProvider(str, Enum):
    """Supported model providers."""

    OPENAI = "openai"
    GEMINI = "gemini"
    GROK = "grok"
    OPENROUTER = "openrouter"


class DevModelOption(TypedDict):
    """One entry of the DEV-ONLY model menu (``constants.llm.DEV_MODEL_OPTIONS``).

    A TypedDict, not a model: it is a fixed in-process shape that is only ever
    spread onto a LangGraph configurable, so it crosses no validation boundary.

    ``model_kwargs`` and ``reasoning``'s effort payload stay ``dict[str, Any]``
    because that is exactly how ``ChatOpenRouter`` declares the fields they are
    bound to — free-form OpenRouter request params, not a shape we own.
    """

    #: Keyed the same as ``PROVIDER_MODELS``/``PROVIDER_PRIORITY`` — the enum is
    #: what stops the menu naming a lane the client cannot resolve.
    provider: LLMProviderName
    model: str
    model_kwargs: dict[str, Any] | None
    reasoning: bool
