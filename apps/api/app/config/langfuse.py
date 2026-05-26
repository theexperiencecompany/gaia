"""Langfuse client initialization and LangChain CallbackHandler factory.

Runs alongside the existing LangSmith @traceable decorators and the Opik
LangChain tracer. The Langfuse v3 SDK exposes a process-wide singleton via
`get_client()` once `Langfuse(...)` has been constructed; the LangChain
`CallbackHandler` then pulls config from that singleton.
"""

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider


@lazy_provider(
    name="langfuse",
    required_keys=[
        settings.LANGFUSE_PUBLIC_KEY,
        settings.LANGFUSE_SECRET_KEY,
        settings.LANGFUSE_HOST,
    ],
    auto_initialize=True,
    is_global_context=True,
    strategy=MissingKeyStrategy.WARN,
    warning_message="Langfuse configuration is missing required settings and will not be initialized.",
)
def init_langfuse() -> Langfuse:
    """Construct the process-wide Langfuse client.

    Subsequent CallbackHandler instances inherit this client's transport.
    """
    return Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
    )


def build_langfuse_callback() -> CallbackHandler | None:
    """Return a LangChain callback handler bound to the global Langfuse client.

    Returns None when Langfuse credentials are unset, so the caller can skip
    attaching the callback without raising. The handler is cheap to construct
    per agent invocation and reads from the singleton initialized above.
    """
    if not (
        settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY and settings.LANGFUSE_HOST
    ):
        return None
    return CallbackHandler()
