"""Langfuse client + LangChain CallbackHandler.

Activates only when LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and
LANGFUSE_HOST are all set; missing any one is a silent no-op so dev runs
without keys stay quiet.

Trace association lives in `RunnableConfig.metadata["langfuse_trace_id"]`
(the standard Langfuse LangChain pattern). `trace_id_for_message` seeds a
deterministic ID from the GAIA assistant `message_id` so `/feedback` can
re-derive it without persisting anything.
"""

import os

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider
from shared.py.wide_events import log


def _langfuse_configured() -> bool:
    """True only when all three Langfuse env vars are non-blank.

    Matches `LazyLoader`'s missing-value semantics — whitespace-only strings
    count as missing, so callbacks stay disabled when the provider itself
    skipped initialization.
    """
    return all(
        isinstance(value, str) and value.strip()
        for value in (
            settings.LANGFUSE_PUBLIC_KEY,
            settings.LANGFUSE_SECRET_KEY,
            settings.LANGFUSE_HOST,
        )
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
    """Construct the process-wide Langfuse client + verify reachability.

    A successful `Langfuse(...)` construction does not test the network. The
    SDK ships traces from a background flush thread that swallows errors, so
    bad creds / DNS / TLS failures normally surface as zero traces in the UI
    with no log line anywhere. We run an explicit auth check here so the bad
    case is one warning at startup instead of a silent black hole.
    """
    # Sentry's OTel integration (sentry-sdk[langgraph]) sets the global
    # TracerProvider before us, so the SDK's `environment` constructor kwarg
    # never reaches the OTel Resource. The env var is the path the SDK reads
    # for Resource attributes; the kwarg additionally tags per-span context.
    # Both are set deliberately.
    os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = settings.ENV
    client = Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
        environment=settings.ENV,
    )
    try:
        if client.auth_check():
            log.info("langfuse_ready", host=settings.LANGFUSE_HOST, environment=settings.ENV)
        else:
            log.warning(
                "langfuse_auth_check_failed",
                host=settings.LANGFUSE_HOST,
                hint="public/secret keys rejected; traces will be dropped",
            )
    except Exception as exc:
        log.warning(
            "langfuse_reachability_check_failed",
            host=settings.LANGFUSE_HOST,
            error=str(exc),
            error_type=type(exc).__name__,
            hint="DNS/TLS/network — traces will be queued and likely dropped",
        )
    return client


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
