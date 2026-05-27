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


_COMPLETE_MESSAGE_PREFIX = "nostream:"


def _extract_complete_message(chunk: str) -> str | None:
    """Pull the assistant text out of the chat stream's final `nostream:` frame.

    GAIA's chat stream emits a single SSE-adjacent line shaped like
    `nostream: {"complete_message": "...", "cancelled": false}` right before
    `data: [DONE]`. We use that line as the trace output so the Langfuse UI
    shows the full assistant reply at the trace level. Every other chunk
    (`data: …`, tool events) returns None and stays uncaptured here — the
    LangChain CallbackHandler has already recorded those as child spans.
    """
    if not chunk.startswith(_COMPLETE_MESSAGE_PREFIX):
        return None
    import json  # noqa: PLC0415

    try:
        payload = json.loads(chunk[len(_COMPLETE_MESSAGE_PREFIX) :].strip())
    except json.JSONDecodeError:
        return None
    complete = payload.get("complete_message")
    return complete if isinstance(complete, str) else None


async def trace_async_stream(
    stream: AsyncGenerator[str, None],
    *,
    message_id: str | None,
    session_id: str | None = None,
    user_id: str | None = None,
    user_input: str | None = None,
    tags: list[str] | None = None,
    name: str = "chat-message",
) -> AsyncGenerator[str, None]:
    """Wrap an async chat stream in a Langfuse trace keyed by `message_id`.

    The trace_id is deterministically derived from `message_id`, so the
    `/messages/{id}/feedback` endpoint can re-derive the same ID later
    without persisting it. Every LangChain callback the inner stream emits
    nests under this parent span.

    `session_id`, `user_id`, and `tags` are pushed onto the parent span via
    `propagate_attributes` so they land on the trace itself (not just on the
    LangChain child spans, where they'd be invisible to the trace view).

    `user_input` populates the trace input column. The trace output is
    filled in once the stream emits its `nostream:` complete-message marker.

    If Langfuse isn't configured (or no message_id is supplied) the stream
    passes through untouched and no Langfuse calls fire.
    """
    trace_id = trace_id_for_message(message_id) if message_id else None
    if trace_id is None:
        async for chunk in stream:
            yield chunk
        return

    from langfuse import get_client, propagate_attributes  # noqa: PLC0415 — defer SDK import

    client = get_client()
    with (
        client.start_as_current_observation(
            name=name,
            as_type="span",
            trace_context={"trace_id": trace_id},
            input=user_input,
        ) as span,
        propagate_attributes(
            session_id=session_id,
            user_id=user_id,
            tags=tags,
        ),
    ):
        complete_message: str | None = None
        try:
            async for chunk in stream:
                if complete_message is None:
                    captured = _extract_complete_message(chunk)
                    if captured is not None:
                        complete_message = captured
                yield chunk
        finally:
            if complete_message is not None:
                span.update(output=complete_message)
