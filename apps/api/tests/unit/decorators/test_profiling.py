"""Unit tests for the profiling decorator.

Covers:
- Decorator disabled when ENABLE_PROFILING is False
- Decorator disabled when pyinstrument is unavailable (PROFILING_AVAILABLE=False)
- Sync and async function profiling when enabled
- Sampling rate behavior (skip profiling when sampled out)
- Slow function warning threshold (> 1.0s)
- Exception propagation through decorated functions
- Profiler error handling in the finally block
- Both @profile_function and @profile_function() usage patterns
- Custom sample_rate override
- Profiler class being None edge case
- functools.wraps metadata preservation
"""

from unittest.mock import MagicMock, patch

import pytest

from app.decorators.profiling import profile_function


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_profiler() -> MagicMock:
    """Create a mock that behaves like pyinstrument.Profiler."""
    profiler = MagicMock()
    profiler.start = MagicMock()
    profiler.stop = MagicMock()
    profiler.output_text = MagicMock(return_value="<profiler output>")
    return profiler


# ---------------------------------------------------------------------------
# Tests: profiling disabled
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProfilingDisabled:
    """When profiling is disabled the decorator should be a transparent pass-through."""

    def test_returns_original_sync_function_when_disabled(self) -> None:
        """If ENABLE_PROFILING=False the decorator returns the original function."""
        with (
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.settings") as mock_settings,
        ):
            mock_settings.ENABLE_PROFILING = False

            def my_func() -> str:
                return "hello"

            decorated = profile_function(my_func)
            assert decorated is my_func

    def test_returns_original_async_function_when_disabled(self) -> None:
        with (
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.settings") as mock_settings,
        ):
            mock_settings.ENABLE_PROFILING = False

            async def my_async() -> str:
                return "async hello"

            decorated = profile_function(my_async)
            assert decorated is my_async

    def test_returns_original_when_profiling_unavailable(self) -> None:
        """If pyinstrument is not installed (PROFILING_AVAILABLE=False), decorator is a no-op."""
        with (
            patch("app.decorators.profiling.PROFILING_AVAILABLE", False),
            patch("app.decorators.profiling.settings") as mock_settings,
        ):
            mock_settings.ENABLE_PROFILING = True

            def my_func() -> int:
                return 42

            decorated = profile_function(my_func)
            assert decorated is my_func

    def test_returns_original_when_both_disabled(self) -> None:
        """When both profiling unavailable and disabled in settings."""
        with (
            patch("app.decorators.profiling.PROFILING_AVAILABLE", False),
            patch("app.decorators.profiling.settings") as mock_settings,
        ):
            mock_settings.ENABLE_PROFILING = False

            def my_func() -> str:
                return "nope"

            decorated = profile_function(my_func)
            assert decorated is my_func

    def test_parenthesized_decorator_disabled(self) -> None:
        """@profile_function() (with parens) also passes through when disabled."""
        with (
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.settings") as mock_settings,
        ):
            mock_settings.ENABLE_PROFILING = False

            def my_func() -> str:
                return "ok"

            decorator = profile_function()
            decorated = decorator(my_func)
            assert decorated is my_func

    def test_parenthesized_decorator_with_sample_rate_still_disabled(self) -> None:
        """Even with a custom sample_rate, disabled settings means no wrapper."""
        with (
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.settings") as mock_settings,
        ):
            mock_settings.ENABLE_PROFILING = False

            def my_func() -> str:
                return "ignored"

            decorated = profile_function(sample_rate=1.0)(my_func)
            assert decorated is my_func


# ---------------------------------------------------------------------------
# Tests: profiling enabled — sync
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSyncProfiling:
    """Sync function profiling when enabled."""

    def test_sync_function_returns_correct_result(self) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            def add(a: int, b: int) -> int:
                return a + b

            result = add(3, 4)

        assert result == 7

    def test_sync_profiler_start_stop_called(self) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            def noop() -> None:
                pass

            noop()

        mock_profiler_instance.start.assert_called_once()
        mock_profiler_instance.stop.assert_called_once()
        mock_profiler_instance.output_text.assert_called_once()

    def test_sync_logs_profile_output(self) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log") as mock_log,
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            def my_fn() -> None:
                pass

            my_fn()

        mock_log.info.assert_called_once()
        call_args = mock_log.info.call_args[0][0]
        assert "Profile for my_fn" in call_args
        assert "<profiler output>" in call_args

    def test_sync_slow_function_warning(self) -> None:
        """Functions taking > 1.0s should trigger a slow-function warning."""
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log") as mock_log,
            patch("app.decorators.profiling.random") as mock_random,
            patch("app.decorators.profiling.time") as mock_time,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5
            # Simulate 2-second execution
            mock_time.time.side_effect = [0.0, 2.0]

            @profile_function
            def slow_fn() -> str:
                return "done"

            result = slow_fn()

        assert result == "done"
        mock_log.warning.assert_called_once_with(
            "slow function",
            function="slow_fn",
            duration_ms=2000.0,
        )

    def test_sync_no_slow_warning_under_threshold(self) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log") as mock_log,
            patch("app.decorators.profiling.random") as mock_random,
            patch("app.decorators.profiling.time") as mock_time,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5
            # Under the 1.0s threshold
            mock_time.time.side_effect = [0.0, 0.5]

            @profile_function
            def fast_fn() -> None:
                pass

            fast_fn()

        mock_log.warning.assert_not_called()

    def test_sync_exception_propagates(self) -> None:
        """Exceptions from the decorated function must re-raise."""
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            def exploding() -> None:
                raise ValueError("boom")

            with pytest.raises(ValueError, match="boom"):
                exploding()

        # Profiler should still be stopped even on exception
        mock_profiler_instance.stop.assert_called_once()

    def test_sync_profiler_stop_error_is_caught(self) -> None:
        """If profiler.stop() raises, it is caught and logged as a warning."""
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_instance.stop.side_effect = RuntimeError("profiler broken")
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log") as mock_log,
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            def ok_fn() -> str:
                return "ok"

            result = ok_fn()

        assert result == "ok"
        assert mock_log.warning.called
        warning_msg = mock_log.warning.call_args[0][0]
        assert "Failed to generate profile" in warning_msg

    def test_sync_profiler_output_text_error_is_caught(self) -> None:
        """If profiler.output_text() raises, it is caught and logged."""
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_instance.output_text.side_effect = RuntimeError("output fail")
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log") as mock_log,
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            def ok_fn() -> str:
                return "fine"

            result = ok_fn()

        assert result == "fine"
        assert mock_log.warning.called
        warning_msg = mock_log.warning.call_args[0][0]
        assert "Failed to generate profile" in warning_msg
        assert "output fail" in warning_msg

    def test_sync_preserves_function_metadata(self) -> None:
        """functools.wraps should preserve __name__, __doc__, etc."""
        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", MagicMock()),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random"),
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0

            @profile_function
            def documented_fn() -> None:
                """This is my docstring."""
                pass

        assert documented_fn.__name__ == "documented_fn"
        assert documented_fn.__doc__ == "This is my docstring."

    def test_sync_passes_args_and_kwargs(self) -> None:
        """Decorated function should correctly forward all arguments."""
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            def join_args(*args: str, sep: str = "-") -> str:
                return sep.join(args)

            result = join_args("a", "b", "c", sep="+")

        assert result == "a+b+c"


# ---------------------------------------------------------------------------
# Tests: profiling enabled — async
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAsyncProfiling:
    """Async function profiling when enabled."""

    async def test_async_function_returns_correct_result(self) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            async def async_add(a: int, b: int) -> int:
                return a + b

            result = await async_add(10, 20)

        assert result == 30

    async def test_async_profiler_start_stop_called(self) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            async def noop_async() -> None:
                pass

            await noop_async()

        mock_profiler_instance.start.assert_called_once()
        mock_profiler_instance.stop.assert_called_once()
        mock_profiler_instance.output_text.assert_called_once()

    async def test_async_logs_profile_output(self) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log") as mock_log,
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            async def my_async_fn() -> None:
                pass

            await my_async_fn()

        mock_log.info.assert_called_once()
        call_args = mock_log.info.call_args[0][0]
        assert "Profile for my_async_fn" in call_args

    async def test_async_slow_function_warning(self) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log") as mock_log,
            patch("app.decorators.profiling.random") as mock_random,
            patch("app.decorators.profiling.time") as mock_time,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5
            mock_time.time.side_effect = [0.0, 1.5]

            @profile_function
            async def slow_async() -> str:
                return "slow"

            result = await slow_async()

        assert result == "slow"
        mock_log.warning.assert_called_once_with(
            "slow function",
            function="slow_async",
            duration_ms=1500.0,
        )

    async def test_async_no_slow_warning_under_threshold(self) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log") as mock_log,
            patch("app.decorators.profiling.random") as mock_random,
            patch("app.decorators.profiling.time") as mock_time,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5
            mock_time.time.side_effect = [0.0, 0.8]

            @profile_function
            async def fast_async() -> None:
                pass

            await fast_async()

        mock_log.warning.assert_not_called()

    async def test_async_exception_propagates(self) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            async def async_explode() -> None:
                raise TypeError("async boom")

            with pytest.raises(TypeError, match="async boom"):
                await async_explode()

        mock_profiler_instance.stop.assert_called_once()

    async def test_async_profiler_output_error_is_caught(self) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_instance.output_text.side_effect = RuntimeError("output fail")
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log") as mock_log,
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            async def ok_async() -> str:
                return "fine"

            result = await ok_async()

        assert result == "fine"
        assert mock_log.warning.called
        warning_msg = mock_log.warning.call_args[0][0]
        assert "Failed to generate profile" in warning_msg

    async def test_async_profiler_stop_error_is_caught(self) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_instance.stop.side_effect = RuntimeError("stop broken")
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log") as mock_log,
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            async def ok_async() -> str:
                return "ok"

            result = await ok_async()

        assert result == "ok"
        assert mock_log.warning.called
        warning_msg = mock_log.warning.call_args[0][0]
        assert "Failed to generate profile" in warning_msg

    async def test_async_preserves_function_metadata(self) -> None:
        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", MagicMock()),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random"),
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0

            @profile_function
            async def my_documented_async() -> None:
                """Async docstring."""
                pass

        assert my_documented_async.__name__ == "my_documented_async"
        assert my_documented_async.__doc__ == "Async docstring."

    async def test_async_passes_args_and_kwargs(self) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            async def async_join(*args: str, sep: str = "-") -> str:
                return sep.join(args)

            result = await async_join("x", "y", sep=".")

        assert result == "x.y"


# ---------------------------------------------------------------------------
# Tests: sampling rate
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSamplingRate:
    """Sampling rate controls whether profiling actually runs."""

    def test_sync_skips_profiling_when_sampled_out(self) -> None:
        """When random() >= sample_rate, the function runs without profiling."""
        mock_profiler_cls = MagicMock()

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 0.1
            # random() returns 0.5 which is >= 0.1 => skip profiling
            mock_random.random.return_value = 0.5

            @profile_function
            def my_fn() -> str:
                return "no profile"

            result = my_fn()

        assert result == "no profile"
        # Profiler should never have been instantiated
        mock_profiler_cls.assert_not_called()

    def test_sync_profiles_when_sampled_in(self) -> None:
        """When random() < sample_rate, profiling runs."""
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 0.5
            # random() returns 0.1 which is < 0.5 => profile
            mock_random.random.return_value = 0.1

            @profile_function
            def my_fn() -> str:
                return "profiled"

            result = my_fn()

        assert result == "profiled"
        mock_profiler_cls.assert_called_once()

    def test_sync_always_profiles_at_rate_1(self) -> None:
        """At sample_rate=1.0, the sampling branch is skipped entirely
        because the guard ``effective_sample_rate < 1.0`` is False."""
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.99

            @profile_function
            def my_fn() -> str:
                return "always"

            my_fn()

        mock_profiler_cls.assert_called_once()

    async def test_async_skips_profiling_when_sampled_out(self) -> None:
        mock_profiler_cls = MagicMock()

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 0.2
            mock_random.random.return_value = 0.8

            @profile_function
            async def my_async_fn() -> str:
                return "skipped"

            result = await my_async_fn()

        assert result == "skipped"
        mock_profiler_cls.assert_not_called()

    async def test_async_profiles_when_sampled_in(self) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 0.5
            mock_random.random.return_value = 0.1

            @profile_function
            async def my_async_fn() -> str:
                return "profiled async"

            result = await my_async_fn()

        assert result == "profiled async"
        mock_profiler_cls.assert_called_once()

    async def test_async_always_profiles_at_rate_1(self) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.99

            @profile_function
            async def my_async_fn() -> str:
                return "always"

            await my_async_fn()

        mock_profiler_cls.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: custom sample_rate override
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCustomSampleRate:
    """The decorator accepts an explicit sample_rate kwarg that overrides settings."""

    def test_custom_rate_zero_always_skips_profiling(self) -> None:
        """profile_function(sample_rate=0.0) should always skip profiling."""
        mock_profiler_cls = MagicMock()

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            # Global rate says always profile
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            # random() returns 0.0 which is >= 0.0 => skip
            mock_random.random.return_value = 0.0

            @profile_function(sample_rate=0.0)
            def my_fn() -> str:
                return "skipped"

            result = my_fn()

        assert result == "skipped"
        mock_profiler_cls.assert_not_called()

    def test_custom_rate_one_always_profiles(self) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            # Global rate is low, but override is 1.0
            mock_settings.PROFILING_SAMPLE_RATE = 0.01
            mock_random.random.return_value = 0.99

            @profile_function(sample_rate=1.0)
            def my_fn() -> str:
                return "profiled"

            my_fn()

        # sample_rate=1.0 means the if-guard is False => always profiles
        mock_profiler_cls.assert_called_once()

    async def test_async_custom_rate_zero_skips(self) -> None:
        mock_profiler_cls = MagicMock()

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.0

            @profile_function(sample_rate=0.0)
            async def my_async() -> str:
                return "skip"

            result = await my_async()

        assert result == "skip"
        mock_profiler_cls.assert_not_called()

    def test_custom_rate_overrides_global_rate(self) -> None:
        """Explicit sample_rate=0.9 should override the global 0.01."""
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 0.01
            # random=0.5 which is < 0.9 => will profile with custom rate
            mock_random.random.return_value = 0.5

            @profile_function(sample_rate=0.9)
            def my_fn() -> str:
                return "profiled"

            my_fn()

        mock_profiler_cls.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: decorator call styles
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDecoratorCallStyles:
    """Test both @profile_function and @profile_function() patterns."""

    def test_bare_decorator_sync(self) -> None:
        """@profile_function (without parens) should work for sync functions."""
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            def bare() -> str:
                return "bare"

            result = bare()

        assert result == "bare"

    def test_parenthesized_decorator_no_args(self) -> None:
        """@profile_function() (with empty parens) should work."""
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function()
            def parens() -> str:
                return "parens"

            result = parens()

        assert result == "parens"

    def test_parenthesized_decorator_with_sample_rate(self) -> None:
        """@profile_function(sample_rate=0.5) should work."""
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            # random returns 0.3 which < 0.5 => profiles
            mock_random.random.return_value = 0.3

            @profile_function(sample_rate=0.5)
            def custom_rate() -> str:
                return "custom"

            result = custom_rate()

        assert result == "custom"
        mock_profiler_cls.assert_called_once()

    async def test_bare_decorator_async(self) -> None:
        """@profile_function (without parens) should work for async functions."""
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            async def async_bare() -> str:
                return "async bare"

            result = await async_bare()

        assert result == "async bare"

    async def test_parenthesized_decorator_async(self) -> None:
        """@profile_function() with async function."""
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function()
            async def async_parens() -> str:
                return "async parens"

            result = await async_parens()

        assert result == "async parens"


# ---------------------------------------------------------------------------
# Tests: Profiler is None edge case
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProfilerNoneEdgeCase:
    """When Profiler class is None but PROFILING_AVAILABLE is True (shouldn't
    normally happen, but the code guards against it with ``if Profiler is not None``)."""

    def test_sync_runs_without_profiler_when_class_is_none(self) -> None:
        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", None),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log") as mock_log,
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            def fn() -> str:
                return "no profiler"

            result = fn()

        assert result == "no profiler"
        # No profile info or warning should be logged — profiler was None
        mock_log.info.assert_not_called()

    async def test_async_runs_without_profiler_when_class_is_none(self) -> None:
        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", None),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log") as mock_log,
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            async def fn() -> str:
                return "no profiler async"

            result = await fn()

        assert result == "no profiler async"
        mock_log.info.assert_not_called()

    def test_sync_exception_still_propagates_when_profiler_none(self) -> None:
        """Even with Profiler=None, exceptions from the function must propagate."""
        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", None),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log"),
            patch("app.decorators.profiling.random") as mock_random,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5

            @profile_function
            def explode() -> None:
                raise RuntimeError("null profiler boom")

            with pytest.raises(RuntimeError, match="null profiler boom"):
                explode()


# ---------------------------------------------------------------------------
# Tests: parametrized slow-function threshold
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSlowFunctionThresholdParametrized:
    """Parametrized tests for the > 1.0s slow function warning threshold."""

    @pytest.mark.parametrize(
        ("duration", "expect_warning"),
        [
            (0.0, False),
            (0.5, False),
            (0.999, False),
            (1.0, False),  # threshold is strictly > 1.0
            (1.001, True),
            (3.0, True),
        ],
        ids=["zero", "half-second", "just-under", "exactly-1s", "just-over", "3s"],
    )
    def test_sync_slow_threshold(self, duration: float, expect_warning: bool) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log") as mock_log,
            patch("app.decorators.profiling.random") as mock_random,
            patch("app.decorators.profiling.time") as mock_time,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5
            mock_time.time.side_effect = [0.0, duration]

            @profile_function
            def fn() -> None:
                pass

            fn()

        if expect_warning:
            mock_log.warning.assert_called_once()
            assert mock_log.warning.call_args[1]["function"] == "fn"
        else:
            mock_log.warning.assert_not_called()

    @pytest.mark.parametrize(
        ("duration", "expect_warning"),
        [
            (0.0, False),
            (1.0, False),
            (1.001, True),
            (5.0, True),
        ],
        ids=["zero", "exactly-1s", "just-over", "5s"],
    )
    async def test_async_slow_threshold(
        self, duration: float, expect_warning: bool
    ) -> None:
        mock_profiler_instance = _make_mock_profiler()
        mock_profiler_cls = MagicMock(return_value=mock_profiler_instance)

        with (
            patch("app.decorators.profiling.settings") as mock_settings,
            patch("app.decorators.profiling.Profiler", mock_profiler_cls),
            patch("app.decorators.profiling.PROFILING_AVAILABLE", True),
            patch("app.decorators.profiling.log") as mock_log,
            patch("app.decorators.profiling.random") as mock_random,
            patch("app.decorators.profiling.time") as mock_time,
        ):
            mock_settings.ENABLE_PROFILING = True
            mock_settings.PROFILING_SAMPLE_RATE = 1.0
            mock_random.random.return_value = 0.5
            mock_time.time.side_effect = [0.0, duration]

            @profile_function
            async def fn() -> None:
                pass

            await fn()

        if expect_warning:
            mock_log.warning.assert_called_once()
            assert mock_log.warning.call_args[1]["function"] == "fn"
        else:
            mock_log.warning.assert_not_called()
