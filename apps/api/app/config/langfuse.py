"""Langfuse client initialization and LangChain CallbackHandler factory.

Runs alongside the existing LangSmith @traceable decorators and the Opik
LangChain tracer. The Langfuse v3+ SDK exposes a process-wide singleton via
`get_client()` once `Langfuse(...)` has been constructed; the LangChain
`CallbackHandler` then pulls config from that singleton.

Activation rule
---------------
Langfuse is only enabled when ALL three credentials are present:
LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST. If any are
missing the provider stays unregistered, `build_langfuse_callback()`
returns None, and the agent runs without a Langfuse callback attached.

This makes Langfuse implicitly opt-in: dropping the keys in any
environment turns it on, leaving them blank turns it off. By
convention dev runs without keys and only ships to Langfuse when a
developer deliberately copies the dev-project keys into their .env.

Environment segregation
-----------------------
Every trace is tagged with `settings.ENV` ("production" / "development")
via the Langfuse `environment` field, so a single Langfuse project
hosts traces from all deployments with a UI-level filter dropdown.
Promoting to fully separate Langfuse projects per environment is a
drop-in change: create the projects in the Langfuse UI, store the new
key pairs in the matching Infisical environments, and nothing else
needs to change.
"""

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider


def _langfuse_configured() -> bool:
    """True when every credential needed to talk to Langfuse is present."""
    return bool(
        settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY and settings.LANGFUSE_HOST
    )


@lazy_provider(
    name="langfuse",
    required_keys=[
        settings.LANGFUSE_PUBLIC_KEY,
        settings.LANGFUSE_SECRET_KEY,
        settings.LANGFUSE_HOST,
    ],
    auto_initialize=True,
    is_global_context=True,
    strategy=MissingKeyStrategy.SILENT,
)
def init_langfuse() -> Langfuse:
    """Construct the process-wide Langfuse client.

    Subsequent CallbackHandler instances inherit this client's transport
    and the environment tag.
    """
    return Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
        environment=settings.ENV,
    )


def build_langfuse_callback() -> CallbackHandler | None:
    """Return a LangChain callback handler bound to the global Langfuse client.

    Returns None when any credential is missing — the caller skips
    attaching the callback and the agent run produces no Langfuse traces.
    The handler is cheap to construct per agent invocation and reads
    from the singleton initialized above.
    """
    if not _langfuse_configured():
        return None
    return CallbackHandler()
