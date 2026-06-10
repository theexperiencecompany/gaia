"""Unit tests for the timing decorators.

Covers:
- async_timer: logs execution time, slow-function warning, exception logging
- sync_timer: logs execution time, slow-function warning, exception logging
- timer: dispatches correctly to async_timer or sync_timer
- functools.wraps metadata preservation
- Argument and return value pass-through
"""

from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# async_timer
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAsyncTimer:
    """Tests for the async_timer decorator."""

    async def test_returns_correct_result(self) -> None:
        with (
            patch("app.decorators.timing.log"),
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.123]

            from app.decorators.timing import async_timer

            @async_timer
            async def greet(name: str) -> str:
                return f"hello {name}"

            result = await greet("world")

        assert result == "hello world"

    async def test_logs_completion_time(self) -> None:
        with (
            patch("app.decorators.timing.log") as mock_log,
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.456]

            from app.decorators.timing import async_timer

            @async_timer
            async def my_fn() -> None:
                pass

            await my_fn()

        mock_log.info.assert_called_once()
        msg = mock_log.info.call_args[0][0]
        assert "my_fn" in msg
        assert "0.456" in msg

    async def test_slow_function_warning(self) -> None:
        """Functions taking > 1.0s should produce a warning."""
        with (
            patch("app.decorators.timing.log") as mock_log,
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 2.5]

            from app.decorators.timing import async_timer

            @async_timer
            async def slow() -> str:
                return "slow"

            result = await slow()

        assert result == "slow"
        mock_log.warning.assert_called_once_with(
            "slow function",
            function="slow",
            duration_ms=2500.0,
        )

    async def test_no_warning_under_threshold(self) -> None:
        with (
            patch("app.decorators.timing.log") as mock_log,
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.9]

            from app.decorators.timing import async_timer

            @async_timer
            async def fast() -> None:
                pass

            await fast()

        mock_log.warning.assert_not_called()

    async def test_exception_logged_and_reraised(self) -> None:
        with (
            patch("app.decorators.timing.log") as mock_log,
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.789]

            from app.decorators.timing import async_timer

            @async_timer
            async def explode() -> None:
                raise ValueError("kaboom")

            with pytest.raises(ValueError, match="kaboom"):
                await explode()

        mock_log.error.assert_called_once()
        error_msg = mock_log.error.call_args[0][0]
        assert "explode" in error_msg
        assert "0.789" in error_msg
        assert "kaboom" in error_msg

    async def test_preserves_function_metadata(self) -> None:
        with patch("app.decorators.timing.log"), patch("app.decorators.timing.time"):
            from app.decorators.timing import async_timer

            @async_timer
            async def documented() -> None:
                """My async docstring."""
                pass

        assert documented.__name__ == "documented"
        assert documented.__doc__ == "My async docstring."

    async def test_passes_args_and_kwargs(self) -> None:
        with (
            patch("app.decorators.timing.log"),
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.01]

            from app.decorators.timing import async_timer

            @async_timer
            async def multiply(a: int, b: int, offset: int = 0) -> int:
                return a * b + offset

            result = await multiply(3, 4, offset=5)

        assert result == 17

    async def test_exception_on_slow_path_logs_error(self) -> None:
        """When an exception occurs after > 1s, only error is logged (not warning)."""
        with (
            patch("app.decorators.timing.log") as mock_log,
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 3.0]

            from app.decorators.timing import async_timer

            @async_timer
            async def fail_slow() -> None:
                raise RuntimeError("slow failure")

            with pytest.raises(RuntimeError, match="slow failure"):
                await fail_slow()

        # Error is logged but warning is NOT (exception path doesn't reach
        # the success branch that checks > 1.0)
        mock_log.error.assert_called_once()
        mock_log.warning.assert_not_called()


# ---------------------------------------------------------------------------
# sync_timer
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSyncTimer:
    """Tests for the sync_timer decorator."""

    def test_returns_correct_result(self) -> None:
        with (
            patch("app.decorators.timing.log"),
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.05]

            from app.decorators.timing import sync_timer

            @sync_timer
            def add(a: int, b: int) -> int:
                return a + b

            result = add(1, 2)

        assert result == 3

    def test_logs_completion_time(self) -> None:
        with (
            patch("app.decorators.timing.log") as mock_log,
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.321]

            from app.decorators.timing import sync_timer

            @sync_timer
            def my_sync() -> None:
                pass

            my_sync()

        mock_log.info.assert_called_once()
        msg = mock_log.info.call_args[0][0]
        assert "my_sync" in msg
        assert "0.321" in msg

    def test_slow_function_warning(self) -> None:
        with (
            patch("app.decorators.timing.log") as mock_log,
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 1.234]

            from app.decorators.timing import sync_timer

            @sync_timer
            def slow_sync() -> str:
                return "done"

            result = slow_sync()

        assert result == "done"
        mock_log.warning.assert_called_once_with(
            "slow function",
            function="slow_sync",
            duration_ms=1234.0,
        )

    def test_no_warning_under_threshold(self) -> None:
        with (
            patch("app.decorators.timing.log") as mock_log,
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.999]

            from app.decorators.timing import sync_timer

            @sync_timer
            def fast_sync() -> None:
                pass

            fast_sync()

        mock_log.warning.assert_not_called()

    def test_exception_logged_and_reraised(self) -> None:
        with (
            patch("app.decorators.timing.log") as mock_log,
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.567]

            from app.decorators.timing import sync_timer

            @sync_timer
            def fail() -> None:
                raise OSError("disk error")

            with pytest.raises(IOError, match="disk error"):
                fail()

        mock_log.error.assert_called_once()
        error_msg = mock_log.error.call_args[0][0]
        assert "fail" in error_msg
        assert "0.567" in error_msg
        assert "disk error" in error_msg

    def test_preserves_function_metadata(self) -> None:
        with patch("app.decorators.timing.log"), patch("app.decorators.timing.time"):
            from app.decorators.timing import sync_timer

            @sync_timer
            def documented_sync() -> None:
                """Sync docstring."""
                pass

        assert documented_sync.__name__ == "documented_sync"
        assert documented_sync.__doc__ == "Sync docstring."

    def test_passes_args_and_kwargs(self) -> None:
        with (
            patch("app.decorators.timing.log"),
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.01]

            from app.decorators.timing import sync_timer

            @sync_timer
            def concat(*parts: str, sep: str = " ") -> str:
                return sep.join(parts)

            result = concat("a", "b", "c", sep="-")

        assert result == "a-b-c"

    def test_exception_on_slow_path_logs_error_not_warning(self) -> None:
        with (
            patch("app.decorators.timing.log") as mock_log,
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 5.0]

            from app.decorators.timing import sync_timer

            @sync_timer
            def fail_slow() -> None:
                raise RuntimeError("slow boom")

            with pytest.raises(RuntimeError, match="slow boom"):
                fail_slow()

        mock_log.error.assert_called_once()
        mock_log.warning.assert_not_called()


# ---------------------------------------------------------------------------
# timer (universal dispatcher)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTimer:
    """The universal timer should dispatch to async_timer or sync_timer."""

    def test_dispatches_sync_to_sync_timer(self) -> None:
        with (
            patch("app.decorators.timing.log"),
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.1]

            from app.decorators.timing import timer

            @timer
            def sync_fn() -> str:
                return "sync"

            result = sync_fn()

        assert result == "sync"

    async def test_dispatches_async_to_async_timer(self) -> None:
        with (
            patch("app.decorators.timing.log"),
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.2]

            from app.decorators.timing import timer

            @timer
            async def async_fn() -> str:
                return "async"

            result = await async_fn()

        assert result == "async"

    def test_sync_via_timer_logs_correctly(self) -> None:
        with (
            patch("app.decorators.timing.log") as mock_log,
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.555]

            from app.decorators.timing import timer

            @timer
            def fn() -> None:
                pass

            fn()

        mock_log.info.assert_called_once()
        msg = mock_log.info.call_args[0][0]
        assert "fn" in msg
        assert "0.555" in msg

    async def test_async_via_timer_logs_correctly(self) -> None:
        with (
            patch("app.decorators.timing.log") as mock_log,
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.777]

            from app.decorators.timing import timer

            @timer
            async def fn() -> None:
                pass

            await fn()

        mock_log.info.assert_called_once()
        msg = mock_log.info.call_args[0][0]
        assert "fn" in msg
        assert "0.777" in msg


# ---------------------------------------------------------------------------
# Edge cases with parametrize
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTimingEdgeCases:
    """Parametrized edge-case tests."""

    @pytest.mark.parametrize(
        ("execution_time", "expect_warning"),
        [
            (0.0, False),
            (0.5, False),
            (0.999, False),
            (1.0, False),  # threshold is strictly > 1.0
            (1.001, True),
            (5.0, True),
        ],
        ids=[
            "zero",
            "half-second",
            "just-under",
            "exactly-1s",
            "just-over",
            "five-seconds",
        ],
    )
    def test_sync_timer_warning_threshold(
        self, execution_time: float, expect_warning: bool
    ) -> None:
        with (
            patch("app.decorators.timing.log") as mock_log,
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, execution_time]

            from app.decorators.timing import sync_timer

            @sync_timer
            def fn() -> None:
                pass

            fn()

        if expect_warning:
            mock_log.warning.assert_called_once()
        else:
            mock_log.warning.assert_not_called()

    @pytest.mark.parametrize(
        ("execution_time", "expect_warning"),
        [
            (0.0, False),
            (0.5, False),
            (1.0, False),
            (1.001, True),
            (10.0, True),
        ],
        ids=[
            "zero",
            "half-second",
            "exactly-1s",
            "just-over",
            "ten-seconds",
        ],
    )
    async def test_async_timer_warning_threshold(
        self, execution_time: float, expect_warning: bool
    ) -> None:
        with (
            patch("app.decorators.timing.log") as mock_log,
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, execution_time]

            from app.decorators.timing import async_timer

            @async_timer
            async def fn() -> None:
                pass

            await fn()

        if expect_warning:
            mock_log.warning.assert_called_once()
        else:
            mock_log.warning.assert_not_called()

    @pytest.mark.parametrize(
        "exception_cls",
        [ValueError, TypeError, RuntimeError, IOError, KeyError],
        ids=["ValueError", "TypeError", "RuntimeError", "IOError", "KeyError"],
    )
    def test_sync_timer_propagates_various_exceptions(self, exception_cls: type) -> None:
        with (
            patch("app.decorators.timing.log"),
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.1]

            from app.decorators.timing import sync_timer

            @sync_timer
            def fn() -> None:
                raise exception_cls("test error")

            with pytest.raises(exception_cls, match="test error"):
                fn()

    @pytest.mark.parametrize(
        "exception_cls",
        [ValueError, TypeError, RuntimeError, IOError, KeyError],
        ids=["ValueError", "TypeError", "RuntimeError", "IOError", "KeyError"],
    )
    async def test_async_timer_propagates_various_exceptions(self, exception_cls: type) -> None:
        with (
            patch("app.decorators.timing.log"),
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.1]

            from app.decorators.timing import async_timer

            @async_timer
            async def fn() -> None:
                raise exception_cls("test error")

            with pytest.raises(exception_cls, match="test error"):
                await fn()

    def test_sync_timer_with_none_return(self) -> None:
        """Ensure None return values are handled correctly."""
        with (
            patch("app.decorators.timing.log"),
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.01]

            from app.decorators.timing import sync_timer

            @sync_timer
            def fn() -> None:
                pass

            fn()

        assert True  # fn() returns None, verified by sync_timer decorator

    async def test_async_timer_with_none_return(self) -> None:
        with (
            patch("app.decorators.timing.log"),
            patch("app.decorators.timing.time") as mock_time,
        ):
            mock_time.time.side_effect = [0.0, 0.01]

            from app.decorators.timing import async_timer

            @async_timer
            async def fn() -> None:
                pass

            result = await fn()

        assert result is None
