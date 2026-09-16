from lmnr import Instruments, Laminar

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider
from shared.py.wide_events import log


@lazy_provider(
    name="laminar",
    required_keys=[settings.LMNR_PROJECT_API_KEY],
    auto_initialize=True,
    is_global_context=True,
    strategy=MissingKeyStrategy.SILENT,
)
def init_laminar() -> bool:
    """Initialize Laminar telemetry once per process.

    ``set_global_tracer_provider=False`` is load-bearing: Latitude owns the
    global provider, and Laminar replacing it would silently reroute every
    vendor's spans. Laminar instruments against its own provider instead.
    Only LangChain/LangGraph auto-instrumentation is enabled — the rest of
    the suite is either OTel paths we don't emit or providers we don't call.
    No-op when LMNR_PROJECT_API_KEY is unset.
    """
    Laminar.initialize(
        project_api_key=settings.LMNR_PROJECT_API_KEY or "",
        instruments={Instruments.LANGCHAIN, Instruments.LANGGRAPH},
        set_global_tracer_provider=False,
    )
    log.info("laminar_ready")
    return True


async def flush_laminar() -> None:
    """Flush queued Laminar spans on shutdown so a restart loses no traces."""
    if not (settings.LMNR_PROJECT_API_KEY or "").strip():
        return
    try:
        Laminar.flush()
    except Exception as exc:
        log.warning(
            "laminar_flush_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
