"""
Profiling middleware for performance monitoring using pyinstrument.

This module provides middleware for profiling HTTP requests with detailed call stack analysis.
Profiling is completely optional and must be explicitly enabled via environment variables.
"""

import random
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from fastapi.responses import HTMLResponse

from app.config.loggers import profiler_logger as logger
from app.config.settings import settings

# Import pyinstrument with fallback
PYINSTRUMENT_AVAILABLE = False
Profiler: type | None = None
try:
    from pyinstrument import Profiler as _Profiler

    Profiler = _Profiler
    PYINSTRUMENT_AVAILABLE = True
    logger.info("PyInstrument profiling available")
except ImportError:
    logger.info("PyInstrument not available. Profiling will be disabled.")


class ProfilingMiddleware(BaseHTTPMiddleware):
    """
    Optional middleware to profile API requests with pyinstrument.

    This middleware provides detailed call stack profiling when:
    1. ENABLE_PROFILING=true is set in environment variables
    2. A request includes the 'profile' query parameter
    3. Random sampling criteria are met (based on PROFILING_SAMPLE_RATE)

    The profiling report is returned as HTML when profiling is active.

    Environment Variables:
        ENABLE_PROFILING: bool = False (must be explicitly enabled)
        PROFILING_SAMPLE_RATE: float = 0.1 (10% sampling rate)

    Usage:
        Add ?profile=1 to any request URL to get a profiling report (when enabled).
    """

    def __init__(self, app):
        super().__init__(app)
        self._log_startup_info()

    def _log_startup_info(self):
        """Log profiling configuration at startup."""
        if not PYINSTRUMENT_AVAILABLE:
            logger.warning(
                "PyInstrument profiling is not available (package not installed)"
            )
            return

        if settings.ENABLE_PROFILING:
            logger.info(
                f"PyInstrument profiling enabled: "
                f"sample_rate={settings.PROFILING_SAMPLE_RATE}"
            )
        else:
            logger.info("PyInstrument profiling disabled (ENABLE_PROFILING=false)")

    async def dispatch(self, request: Request, call_next) -> Response:
        # Check if profiling is available and enabled
        if (
            not settings.ENABLE_PROFILING
            or not PYINSTRUMENT_AVAILABLE
            or Profiler is None
        ):
            return await call_next(request)

        # Check if profiling is explicitly requested
        profiling_requested = request.query_params.get("profile", "").lower() in (
            "1",
            "true",
            "yes",
        )

        # Apply sampling rate for automatic profiling
        should_profile = profiling_requested or (
            settings.PROFILING_SAMPLE_RATE > 0
            and random.random() < settings.PROFILING_SAMPLE_RATE  # nosec: B311
        )

        if not should_profile:
            return await call_next(request)

        # Configure and start profiler with basic configuration
        profiler = Profiler()

        try:
            profiler.start()
            response = await call_next(request)
            profiler.stop()

            # If profiling was explicitly requested via query param, return HTML report
            if profiling_requested:
                html_output = profiler.output_html()
                return HTMLResponse(html_output)
            else:
                # For sampled requests, log the actual profiling results and return normal response
                try:
                    # Get text output for logging
                    text_output = profiler.output_text()
                    logger.info(
                        f"Profiling Results for {request.method} {request.url.path}:\n{text_output}"
                    )
                except Exception as profile_error:
                    logger.warning(
                        f"Could not generate profiling output for {request.method} {request.url.path}: {profile_error}"
                    )
                    logger.info(
                        f"Profiled {request.method} {request.url.path} (output generation failed)"
                    )
                return response

        except Exception as e:
            profiler.stop()
            logger.exception(
                f"Profiling error during {request.method} {request.url.path}: {str(e)}"
            )
            # Always return the original response on error
            return await call_next(request)
