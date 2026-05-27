"""Langfuse client + LangChain CallbackHandler + chat-stream tracing helpers.

Activates only when LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and
LANGFUSE_HOST are all set; missing any one is a silent no-op so dev runs
without keys stay quiet. Trace IDs are deterministic on the GAIA
assistant `message_id`, which lets `/messages/{id}/feedback` re-derive
the trace ID without persisting it anywhere.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import json
import os
from typing import Any

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider


def _langfuse_configured() -> bool:
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
    # Sentry's OTel integration (sentry-sdk[langgraph]) installs the global
    # TracerProvider first, which means the SDK's `environment` constructor
    # kwarg never makes it onto the Resource. Setting the env var here is
    # what the SDK actually reads from in that scenario.
    os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = settings.ENV
    return Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
        environment=settings.ENV,
    )


def build_langfuse_callback() -> CallbackHandler | None:
    """LangChain callback bound to the global client, or None if disabled."""
    if not _langfuse_configured():
        return None
    return CallbackHandler()


def trace_id_for_message(message_id: str) -> str | None:
    """Deterministic Langfuse trace_id seeded from a GAIA assistant message_id."""
    if not _langfuse_configured():
        return None
    return Langfuse.create_trace_id(seed=message_id)


def capture_trace_context() -> dict[str, str] | None:
    """Snapshot the active Langfuse trace + span IDs.

    Used at any boundary where execution hops to a separate asyncio task
    (e.g. `call_executor` → background runner) so the child can re-attach
    via `start_as_current_observation(trace_context=...)`. Returns None
    when Langfuse is unconfigured or no span is active.
    """
    if not _langfuse_configured():
        return None
    from langfuse import get_client  # noqa: PLC0415

    client = get_client()
    trace_id = client.get_current_trace_id()
    span_id = client.get_current_observation_id()
    if not trace_id:
        return None
    captured: dict[str, str] = {"trace_id": trace_id}
    if span_id:
        captured["parent_span_id"] = span_id
    return captured


@asynccontextmanager
async def trace_child_observation(
    trace_context: dict[str, str] | None,
    *,
    name: str,
    input: Any = None,
):
    """Open a Langfuse agent observation nested under a previously-captured trace_context.

    Bridges asyncio-task boundaries where OTel context doesn't auto-propagate:
    the parent captures via `capture_trace_context()`, hands the dict to the
    child task, the child wraps its work in this context manager so its
    spans land under the parent trace instead of starting a new orphan trace.

    No-op (yields None) when no trace_context was captured. The yielded span
    is the active observation — set `.update(output=...)` before exiting.
    """
    if not trace_context or not _langfuse_configured():
        yield None
        return

    from langfuse import get_client  # noqa: PLC0415
    from langfuse.types import TraceContext  # noqa: PLC0415

    tc: TraceContext = {"trace_id": trace_context["trace_id"]}
    parent_span_id = trace_context.get("parent_span_id")
    if parent_span_id:
        tc["parent_span_id"] = parent_span_id

    client = get_client()
    with client.start_as_current_observation(
        name=name,
        as_type="agent",
        trace_context=tc,
        input=input,
    ) as span:
        yield span


_COMPLETE_MESSAGE_PREFIX = "nostream:"


def _extract_complete_message(chunk: str) -> str | None:
    """Pull the assistant text out of the chat stream's final `nostream:` frame."""
    if not chunk.startswith(_COMPLETE_MESSAGE_PREFIX):
        return None
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
    """Wrap a chat stream in a Langfuse trace seeded by `message_id`.

    `session_id` / `user_id` / `tags` land on the trace itself via
    `propagate_attributes` (the LangChain callback's metadata path only
    reaches the LangChain child span, not the trace root). `user_input`
    fills the trace input column; `output` is set from the stream's
    final `nostream:` complete-message frame. No-op when Langfuse is
    unconfigured or no message_id is supplied.
    """
    trace_id = trace_id_for_message(message_id) if message_id else None
    if trace_id is None:
        async for chunk in stream:
            yield chunk
        return

    from langfuse import get_client, propagate_attributes  # noqa: PLC0415

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
