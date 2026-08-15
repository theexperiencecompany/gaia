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
import threading

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from opentelemetry.sdk.trace import TracerProvider

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider
from shared.py.wide_events import log

# How long process start will wait for the reachability check below. A healthy
# Langfuse answers in milliseconds, so this only bites when it is down or slow —
# exactly when startup must not be held up. It cannot be expressed as an SDK
# timeout: `Langfuse(timeout=...)` bounds a single HTTP attempt, but auth_check
# retries internally and takes ~120s against an unreachable host regardless of
# the value passed (measured at both 2s and 5s).
LANGFUSE_AUTH_CHECK_WAIT_SECONDS = 5


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
    with no log line anywhere. We run an explicit auth check so the bad case is
    one warning instead of a silent black hole — but off the startup path, since
    the check can otherwise block a process start for two minutes (see
    ``LANGFUSE_AUTH_CHECK_WAIT_SECONDS``).
    """
    # Sentry's OTel integration (sentry-sdk[langgraph]) sets the global
    # TracerProvider before us, so the SDK's `environment` constructor kwarg
    # never reaches the OTel Resource. The env var is the path the SDK reads
    # for Resource attributes; the kwarg additionally tags per-span context.
    # Both are set deliberately.
    os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = settings.ENV
    # Isolated TracerProvider (langfuse's official "Option C" for coexisting with
    # Sentry). Sentry's OTel integration claims the GLOBAL TracerProvider first;
    # if we let langfuse fall back to it, langfuse rides Sentry's provider and
    # per-trace attributes set by the LangChain callback — session_id, user_id —
    # never land (confirmed: prod had Sentry on → 0 traces with session/user; dev
    # had Sentry off → session/user present). Handing langfuse its own provider
    # keeps its tracing independent of Sentry's sampling/propagation so those
    # attributes attach. Trade-off: spans whose parent lives only in Sentry's
    # provider may look orphaned. Environment still tags per-span via the kwarg +
    # LANGFUSE_TRACING_ENVIRONMENT above.
    client = Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
        environment=settings.ENV,
        tracer_provider=TracerProvider(),
    )
    # Daemon thread, joined with a deadline: the check is a diagnostic, and
    # nothing below it depends on the answer, so a Langfuse outage must cost
    # startup a bounded wait rather than the SDK's full internal retry budget.
    # Daemon so a still-running check can never hold up interpreter shutdown.
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
