"""Unit tests for the optional pyinstrument profiling middleware.

Covers every ProfilingMiddleware decision branch — disabled/passthrough,
explicit ``?profile=`` query, random sampling, sampled output generation
failure, and the exception fallback — plus the startup log lines. pyinstrument
(``Profiler`` / ``PYINSTRUMENT_AVAILABLE``), ``settings`` and the wide-event
logger are fully mocked, so the tests are hermetic and never depend on the
package actually being installed.
"""

from collections.abc import Iterator
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.responses import HTMLResponse
import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.api.v1.middleware.profiling import ProfilingMiddleware
from app.constants.log_tags import LogTag

MODULE = "app.api.v1.middleware.profiling"
REQUEST_PATH = "/api/v1/test"

_EXPLICIT_PROFILE_VALUES = ("1", "true", "yes")


def _make_request(*, query: str = "", method: str = "GET") -> Request:
    """Build a minimal ASGI scope request the middleware can inspect."""
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": REQUEST_PATH,
        "raw_path": REQUEST_PATH.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 8000),
        "state": {},
    }
    return Request(scope)


@pytest.fixture
def profiling_env() -> Iterator[SimpleNamespace]:
    """Patch every seam the middleware touches, defaulting to "enabled".

    Yields the settings namespace, the mocked Profiler class and instance, and
    the mocked wide-event logger. Tests mutate ``settings`` or re-patch the
    module attributes directly for the case they exercise.
    """
    with ExitStack() as stack:
        settings = SimpleNamespace(ENABLE_PROFILING=True, PROFILING_SAMPLE_RATE=1.0)
        stack.enter_context(patch(f"{MODULE}.settings", settings))
        stack.enter_context(patch(f"{MODULE}.PYINSTRUMENT_AVAILABLE", True))
        profiler_cls = MagicMock(name="Profiler")
        stack.enter_context(patch(f"{MODULE}.Profiler", profiler_cls))
        mock_log = MagicMock(name="wide_event_log")
        stack.enter_context(patch(f"{MODULE}.log", mock_log))
        yield SimpleNamespace(
            settings=settings,
            profiler_cls=profiler_cls,
            profiler=profiler_cls.return_value,
            log=mock_log,
        )


@pytest.fixture
def middleware(profiling_env: SimpleNamespace) -> ProfilingMiddleware:
    """Middleware instance with all seams patched; startup logging erased."""
    mw = ProfilingMiddleware(MagicMock())
    profiling_env.log.reset_mock()
    return mw


# ---------------------------------------------------------------------------
# _log_startup_info (fired from __init__)
# ---------------------------------------------------------------------------


class TestStartupInfo:
    def test_warns_when_pyinstrument_unavailable(self, profiling_env: SimpleNamespace) -> None:
        with patch(f"{MODULE}.PYINSTRUMENT_AVAILABLE", False):
            ProfilingMiddleware(MagicMock())
        profiling_env.log.warning.assert_called_once_with(
            f"{LogTag.API} PyInstrument profiling is not available (package not installed)"
        )
        profiling_env.log.info.assert_not_called()

    def test_info_when_enabled(self, profiling_env: SimpleNamespace) -> None:
        ProfilingMiddleware(MagicMock())
        profiling_env.log.info.assert_called_once_with(
            f"{LogTag.API} PyInstrument profiling enabled",
            sample_rate=profiling_env.settings.PROFILING_SAMPLE_RATE,
        )
        profiling_env.log.warning.assert_not_called()

    def test_info_when_disabled(self, profiling_env: SimpleNamespace) -> None:
        profiling_env.settings.ENABLE_PROFILING = False
        ProfilingMiddleware(MagicMock())
        profiling_env.log.info.assert_called_once_with(
            f"{LogTag.API} PyInstrument profiling disabled (ENABLE_PROFILING=false)"
        )
        profiling_env.log.warning.assert_not_called()


# ---------------------------------------------------------------------------
# dispatch — passthrough (no profiling)
# ---------------------------------------------------------------------------


class TestDispatchPassthrough:
    async def test_passthrough_when_profiling_disabled(
        self, profiling_env: SimpleNamespace, middleware: ProfilingMiddleware
    ) -> None:
        profiling_env.settings.ENABLE_PROFILING = False
        request = _make_request(query="profile=1")
        call_next = AsyncMock(return_value=Response(content=b"ok"))
        response = await middleware.dispatch(request, call_next)
        assert response is call_next.return_value
        call_next.assert_awaited_once_with(request)
        profiling_env.profiler_cls.assert_not_called()
        profiling_env.log.assert_not_called()

    async def test_passthrough_when_pyinstrument_unavailable(
        self, profiling_env: SimpleNamespace, middleware: ProfilingMiddleware
    ) -> None:
        with patch(f"{MODULE}.PYINSTRUMENT_AVAILABLE", False):
            request = _make_request()
            call_next = AsyncMock(return_value=Response(content=b"ok"))
            response = await middleware.dispatch(request, call_next)
        assert response is call_next.return_value
        call_next.assert_awaited_once_with(request)
        profiling_env.profiler_cls.assert_not_called()

    async def test_passthrough_when_profiler_none(
        self, profiling_env: SimpleNamespace, middleware: ProfilingMiddleware
    ) -> None:
        with patch(f"{MODULE}.Profiler", None):
            request = _make_request()
            call_next = AsyncMock(return_value=Response(content=b"ok"))
            response = await middleware.dispatch(request, call_next)
        assert response is call_next.return_value
        call_next.assert_awaited_once_with(request)
        profiling_env.profiler_cls.assert_not_called()


# ---------------------------------------------------------------------------
# dispatch — explicit ?profile= query → HTML report
# ---------------------------------------------------------------------------


class TestDispatchExplicitProfile:
    @pytest.mark.parametrize("value", _EXPLICIT_PROFILE_VALUES)
    async def test_returns_html_report(
        self,
        profiling_env: SimpleNamespace,
        middleware: ProfilingMiddleware,
        value: str,
    ) -> None:
        profiling_env.profiler.output_html.return_value = "<html>report</html>"
        request = _make_request(query=f"profile={value}")
        call_next = AsyncMock(return_value=Response(content=b"ok"))
        response = await middleware.dispatch(request, call_next)
        assert isinstance(response, HTMLResponse)
        assert response.body == b"<html>report</html>"
        profiling_env.profiler.start.assert_called_once_with()
        profiling_env.profiler.stop.assert_called_once_with()
        profiling_env.profiler.output_html.assert_called_once_with()
        call_next.assert_awaited_once_with(request)
        profiling_env.log.assert_not_called()

    async def test_profile_value_is_case_insensitive(
        self, profiling_env: SimpleNamespace, middleware: ProfilingMiddleware
    ) -> None:
        profiling_env.profiler.output_html.return_value = "<html>report</html>"
        request = _make_request(query="profile=TRUE")
        call_next = AsyncMock(return_value=Response(content=b"ok"))
        response = await middleware.dispatch(request, call_next)
        assert isinstance(response, HTMLResponse)
        assert response.body == b"<html>report</html>"


# ---------------------------------------------------------------------------
# dispatch — random sampling
# ---------------------------------------------------------------------------


class TestDispatchSampling:
    async def test_samples_when_random_below_rate(
        self, profiling_env: SimpleNamespace, middleware: ProfilingMiddleware
    ) -> None:
        profiling_env.settings.PROFILING_SAMPLE_RATE = 0.5
        profiling_env.profiler.output_text.return_value = "text report"
        request = _make_request()
        original = Response(content=b"ok")
        call_next = AsyncMock(return_value=original)
        with patch("random.random", return_value=0.1):
            response = await middleware.dispatch(request, call_next)
        assert response is original
        profiling_env.profiler.start.assert_called_once_with()
        profiling_env.profiler.stop.assert_called_once_with()
        profiling_env.log.info.assert_called_once_with(
            f"{LogTag.API} Profiling Results",
            method="GET",
            path=REQUEST_PATH,
            profile_output="text report",
        )

    async def test_skips_when_random_at_or_above_rate(
        self, profiling_env: SimpleNamespace, middleware: ProfilingMiddleware
    ) -> None:
        profiling_env.settings.PROFILING_SAMPLE_RATE = 0.5
        request = _make_request()
        call_next = AsyncMock(return_value=Response(content=b"ok"))
        with patch("random.random", return_value=0.5):
            response = await middleware.dispatch(request, call_next)
        assert response is call_next.return_value
        call_next.assert_awaited_once_with(request)
        profiling_env.profiler_cls.assert_not_called()
        profiling_env.log.assert_not_called()

    @pytest.mark.parametrize("rate", [0.0, -0.5])
    async def test_never_samples_with_non_positive_rate(
        self,
        profiling_env: SimpleNamespace,
        middleware: ProfilingMiddleware,
        rate: float,
    ) -> None:
        profiling_env.settings.PROFILING_SAMPLE_RATE = rate
        request = _make_request()
        call_next = AsyncMock(return_value=Response(content=b"ok"))
        with patch("random.random") as mock_random:
            response = await middleware.dispatch(request, call_next)
        assert response is call_next.return_value
        mock_random.assert_not_called()
        profiling_env.profiler_cls.assert_not_called()

    @pytest.mark.parametrize("value", ["0", "false", "no", "", "1x"])
    async def test_non_matching_profile_value_falls_back_to_sampling(
        self,
        profiling_env: SimpleNamespace,
        middleware: ProfilingMiddleware,
        value: str,
    ) -> None:
        profiling_env.profiler.output_text.return_value = "text report"
        request = _make_request(query=f"profile={value}")
        original = Response(content=b"ok")
        call_next = AsyncMock(return_value=original)
        with patch("random.random", return_value=0.0):
            response = await middleware.dispatch(request, call_next)
        assert response is original
        profiling_env.profiler.start.assert_called_once_with()
        profiling_env.log.info.assert_called_once_with(
            f"{LogTag.API} Profiling Results",
            method="GET",
            path=REQUEST_PATH,
            profile_output="text report",
        )


# ---------------------------------------------------------------------------
# dispatch — sampled output generation failure
# ---------------------------------------------------------------------------


class TestDispatchSampledOutputFailure:
    async def test_logs_warning_and_returns_original_response(
        self, profiling_env: SimpleNamespace, middleware: ProfilingMiddleware
    ) -> None:
        profiling_env.profiler.output_text.side_effect = RuntimeError("gen boom")
        request = _make_request()
        original = Response(content=b"ok")
        call_next = AsyncMock(return_value=original)
        with patch("random.random", return_value=0.0):
            response = await middleware.dispatch(request, call_next)
        assert response is original
        profiling_env.profiler.stop.assert_called_once_with()
        profiling_env.log.warning.assert_called_once_with(
            f"{LogTag.API} Could not generate profiling output",
            method="GET",
            path=REQUEST_PATH,
            error_type="RuntimeError",
            error="gen boom",
        )
        profiling_env.log.info.assert_called_once_with(
            f"{LogTag.API} Profiled request (output generation failed)",
            method="GET",
            path=REQUEST_PATH,
        )


# ---------------------------------------------------------------------------
# dispatch — exception fallback (log, retry call_next once)
# ---------------------------------------------------------------------------


class TestDispatchExceptionFallback:
    async def test_profiler_start_failure_logs_and_retries(
        self, profiling_env: SimpleNamespace, middleware: ProfilingMiddleware
    ) -> None:
        profiling_env.profiler.start.side_effect = RuntimeError("start boom")
        request = _make_request()
        # The try branch never reaches call_next, so the fallback retry is the
        # first (and only) invocation.
        retry_response = Response(content=b"ok")
        call_next = AsyncMock(return_value=retry_response)
        response = await middleware.dispatch(request, call_next)
        assert response is retry_response
        call_next.assert_awaited_once_with(request)
        profiling_env.profiler.stop.assert_called_once_with()
        profiling_env.log.exception.assert_called_once_with(
            f"{LogTag.API} Profiling error",
            method="GET",
            path=REQUEST_PATH,
            error_type="RuntimeError",
            error="start boom",
        )

    async def test_call_next_failure_logs_and_retries(
        self, profiling_env: SimpleNamespace, middleware: ProfilingMiddleware
    ) -> None:
        request = _make_request()
        retry_response = Response(content=b"ok")
        call_next = AsyncMock(side_effect=[RuntimeError("boom"), retry_response])
        response = await middleware.dispatch(request, call_next)
        assert response is retry_response
        assert call_next.await_count == 2
        profiling_env.profiler.stop.assert_called_once_with()
        profiling_env.log.exception.assert_called_once_with(
            f"{LogTag.API} Profiling error",
            method="GET",
            path=REQUEST_PATH,
            error_type="RuntimeError",
            error="boom",
        )

    async def test_retry_failure_propagates(
        self, profiling_env: SimpleNamespace, middleware: ProfilingMiddleware
    ) -> None:
        request = _make_request()
        call_next = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            await middleware.dispatch(request, call_next)
        assert call_next.await_count == 2
        profiling_env.profiler.stop.assert_called_once_with()
