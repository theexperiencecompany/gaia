"""Langfuse client + LangChain CallbackHandler.

Activates only when LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and
LANGFUSE_HOST are all set; missing any one is a silent no-op so dev runs
without keys stay quiet.

Trace association lives in RunnableConfig.metadata["langfuse_trace_id"]
(the standard Langfuse LangChain pattern). trace_id_for_message seeds a
deterministic ID from the GAIA assistant message_id so /feedback can
re-derive it without persisting anything.
"""

import os
import threading

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from opentelemetry.sdk.trace import TracerProvider

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider
from shared.py.wide_events import log

# Not an SDK timeout: auth_check retries internally and takes ~120s against
# an unreachable host regardless of the value passed (measured at 2s and 5s).
LANGFUSE_AUTH_CHECK_WAIT_SECONDS = 5


def _langfuse_configured() -> bool:
    """Return True only when all three Langfuse env vars are non-blank.

    Matches LazyLoader's missing-value semantics — whitespace-only strings
    count as missing.
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
    """Construct the process-wide Langfuse client and verify reachability.

    A successful construction does not test the network — the SDK's background
    flush thread swallows errors, so bad creds/DNS/TLS normally show up as zero
    traces with no log line. The reachability check therefore runs off the
    startup path (see LANGFUSE_AUTH_CHECK_WAIT_SECONDS) instead of blocking it.
    """
    # Sentry's OTel integration sets the global TracerProvider first, so the
    # SDK's `environment` kwarg never reaches the OTel Resource; the env var is
    # the path it reads instead. Both are set deliberately.
    os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = settings.ENV
    # Isolated TracerProvider (langfuse's "Option C"): falling back to Sentry's
    # global provider drops per-trace attributes (session_id, user_id) —
    # confirmed via prod/dev trace comparison. Orphaned-looking spans are the trade-off.
    client = Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
        environment=settings.ENV,
        tracer_provider=TracerProvider(),
    )
    # Diagnostic only — a Langfuse outage costs a bounded wait, not the SDK's
    # full retry budget. Daemon so a still-running check can't block shutdown.
    checker = threading.Thread(
        target=_log_reachability, args=(client,), name="langfuse-auth-check", daemon=True
    )
    checker.start()
    checker.join(LANGFUSE_AUTH_CHECK_WAIT_SECONDS)
    if checker.is_alive():
        log.warning(
            "langfuse_reachability_check_timed_out",
            host=settings.LANGFUSE_HOST,
            waited_seconds=LANGFUSE_AUTH_CHECK_WAIT_SECONDS,
            hint="Langfuse slow or unreachable; startup continued, traces likely dropped",
        )
    return client


def _log_reachability(client: Langfuse) -> None:
    """Report whether Langfuse is reachable and the keys are accepted.

    Runs off the startup path (see the caller), so it may log after the process
    is already serving — or not at all, if the process exits first.
    """
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
