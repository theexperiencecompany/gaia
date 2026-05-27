"""Langfuse client initialization, callback handler, and tracing helpers.

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
via the Langfuse `environment` field, plus traces go to a different
project per environment (the API key in Infisical decides the project,
not the code). The env tag is set defensively in case a key gets swapped.

Per-message trace IDs
---------------------
`trace_id_for_message(message_id)` derives a deterministic Langfuse
trace_id from a GAIA `bot_message_id` via the SDK's seeded ID helper.
The chat agent wraps each run in a span bound to that trace_id, and
the `/messages/{id}/feedback` endpoint re-derives the same ID to attach
thumbs-up/down scores without persisting the trace_id anywhere.
"""

from collections.abc import AsyncGenerator
import os

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
    and the environment tag. We set LANGFUSE_TRACING_ENVIRONMENT in the
    process env BEFORE constructing the client because Sentry's OTel
    integration (sentry-sdk[langgraph]) sets the global TracerProvider
    first, so Langfuse falls back to reading the environment from this
    env var rather than installing its own TracerProvider with the
    constructor kwarg as a Resource attribute.
    """
    os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = settings.ENV
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


def trace_id_for_message(message_id: str) -> str | None:
    """Derive a deterministic Langfuse trace_id from a GAIA assistant message_id.

    Returns None when Langfuse isn't configured. The mapping is one-way
    hashed inside the SDK (`Langfuse.create_trace_id(seed=...)`) so the
    same `message_id` always produces the same trace_id without storing
    anything in MongoDB. This lets the feedback endpoint re-derive the
    trace_id later without a lookup.
    """
    if not _langfuse_configured():
        return None
    return Langfuse.create_trace_id(seed=message_id)


async def trace_async_stream(
    stream: AsyncGenerator[str, None],
    *,
    message_id: str | None,
    name: str = "chat-message",
) -> AsyncGenerator[str, None]:
    """Wrap an async chat stream in a Langfuse span keyed by `message_id`.

    Every LangChain callback the inner stream emits nests under this
    parent span, so the whole agent run (LLM calls, sub-agent handoffs,
    tool invocations) lands as one trace whose ID is deterministically
    derived from `message_id`. The feedback endpoint re-derives the
    same ID via `trace_id_for_message()` to attach scores.

    If Langfuse isn't configured (or no message_id is supplied) the
    stream passes through untouched, no span is opened, and no overhead
    is paid.
    """
    trace_id = trace_id_for_message(message_id) if message_id else None
    if trace_id is None:
        async for chunk in stream:
            yield chunk
        return

    from langfuse import get_client  # noqa: PLC0415 — deferred to avoid SDK import at module load

    client = get_client()
    with client.start_as_current_observation(
        name=name,
        as_type="span",
        trace_context={"trace_id": trace_id},
    ):
        async for chunk in stream:
            yield chunk
