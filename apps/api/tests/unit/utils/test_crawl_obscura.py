"""Unit tests for app.utils.crawl_obscura — the shared crawl engine's process manager."""

import asyncio
from collections.abc import Awaitable, Iterator
import subprocess
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from app.config.settings import settings
from app.utils import crawl_obscura

_BASE_PORT = 39222
# Pinned independently of the module so a change to either constant shows up here.
_PORT_ATTEMPTS = 5
_BIND_SETTLE_SECONDS = 0.5


class FakeProcess:
    """Stand in for asyncio.subprocess.Process, recording terminate/kill/wait."""

    def __init__(
        self,
        returncode: int | None = None,
        wait_error: type[BaseException] | None = None,
        terminate_error: type[BaseException] | None = None,
    ):
        self.returncode = returncode
        self.wait_error = wait_error
        self.terminate_error = terminate_error
        self.terminated = False
        self.killed = False
        self.waited = False

    def terminate(self) -> None:
        self.terminated = True
        if self.terminate_error is not None:
            raise self.terminate_error()

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.waited = True
        if self.wait_error is not None:
            raise self.wait_error()
        return self.returncode or 0


class _Spawner:
    """Serves one FakeProcess per port attempt and records the argv it was given."""

    def __init__(self, processes: list[FakeProcess]):
        self._processes = processes
        self.argvs: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []

    async def __call__(self, *argv: str, **kwargs: Any) -> FakeProcess:
        self.argvs.append(list(argv))
        self.kwargs.append(kwargs)
        return self._processes[len(self.argvs) - 1]

    @property
    def ports(self) -> list[int]:
        return [int(argv[argv.index("--port") + 1]) for argv in self.argvs]


@pytest.fixture(autouse=True)
def _isolated_engine_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No engine at the start of a test, and none left behind for the next one."""
    monkeypatch.setattr(settings, "OBSCURA_CRAWL_PORT", _BASE_PORT)
    monkeypatch.setattr(settings, "OBSCURA_BIN", "/usr/bin/obscura")
    crawl_obscura._engine = None
    yield
    crawl_obscura._engine = None


def _running(monkeypatch: pytest.MonkeyPatch, proc: FakeProcess) -> None:
    """Install proc as the engine on record, published at the base port."""
    engine = crawl_obscura._CrawlEngine(
        proc=cast(asyncio.subprocess.Process, proc), cdp_url=f"http://127.0.0.1:{_BASE_PORT}"
    )
    monkeypatch.setattr(crawl_obscura, "_engine", engine)


@pytest.fixture
def no_bind_settle(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Skip the real bind-settle wait, recording every duration the module asked for."""
    recorded: list[float] = []
    real_sleep = asyncio.sleep

    async def spy(delay: float, *args: Any, **kwargs: Any) -> Any:
        recorded.append(delay)
        return await real_sleep(0, *args, **kwargs)

    monkeypatch.setattr(asyncio, "sleep", spy)
    return recorded


def _spawn(monkeypatch: pytest.MonkeyPatch, processes: list[FakeProcess]) -> _Spawner:
    spawner = _Spawner(processes)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawner)
    return spawner


def _record_wait_for_timeouts(monkeypatch: pytest.MonkeyPatch) -> list[float | None]:
    """Record every deadline the module hands asyncio.wait_for.

    The shutdown grace period never reaches a return value or an error message,
    so the timeout argument is the only place it is observable.
    """
    recorded: list[float | None] = []
    real_wait_for = asyncio.wait_for

    async def spy(awaitable: Awaitable[Any], timeout: float | None = None) -> Any:
        recorded.append(timeout)
        return await real_wait_for(awaitable, timeout)

    monkeypatch.setattr(asyncio, "wait_for", spy)
    return recorded


@patch("app.utils.crawl_obscura.poll_obscura_endpoint", new_callable=AsyncMock)
class TestEnsureCrawlObscura:
    """Launch, reuse, relaunch, and the upward port probe."""

    async def test_launches_on_the_base_port_and_returns_its_cdp_url(
        self, mock_poll: AsyncMock, monkeypatch: pytest.MonkeyPatch, no_bind_settle: list[float]
    ) -> None:
        spawner = _spawn(monkeypatch, [FakeProcess()])

        url = await crawl_obscura.ensure_crawl_obscura()

        assert url == f"http://127.0.0.1:{_BASE_PORT}"
        assert spawner.ports == [_BASE_PORT]
        assert mock_poll.await_args.args == (_BASE_PORT,)

    async def test_a_second_caller_reuses_the_running_engine(
        self, mock_poll: AsyncMock, monkeypatch: pytest.MonkeyPatch, no_bind_settle: list[float]
    ) -> None:
        spawner = _spawn(monkeypatch, [FakeProcess(), FakeProcess()])

        first = await crawl_obscura.ensure_crawl_obscura()
        second = await crawl_obscura.ensure_crawl_obscura()

        assert first == second
        assert spawner.ports == [_BASE_PORT]

    async def test_an_engine_that_died_is_relaunched(
        self, mock_poll: AsyncMock, monkeypatch: pytest.MonkeyPatch, no_bind_settle: list[float]
    ) -> None:
        dead = FakeProcess()
        spawner = _spawn(monkeypatch, [dead, FakeProcess()])

        await crawl_obscura.ensure_crawl_obscura()
        dead.returncode = 1
        url = await crawl_obscura.ensure_crawl_obscura()

        # Relaunched on the base port again — the dead one no longer holds it.
        assert spawner.ports == [_BASE_PORT, _BASE_PORT]
        assert url == f"http://127.0.0.1:{_BASE_PORT}"

    async def test_a_port_whose_process_exits_immediately_is_skipped(
        self, mock_poll: AsyncMock, monkeypatch: pytest.MonkeyPatch, no_bind_settle: list[float]
    ) -> None:
        spawner = _spawn(monkeypatch, [FakeProcess(returncode=1), FakeProcess()])

        url = await crawl_obscura.ensure_crawl_obscura()

        assert url == f"http://127.0.0.1:{_BASE_PORT + 1}"
        assert spawner.ports == [_BASE_PORT, _BASE_PORT + 1]
        # The exited process is never polled — a taken port is a fast exit we skip past.
        assert mock_poll.await_args_list == [((_BASE_PORT + 1,), {})]
        # Each attempt waits out the bind-settle window before reading returncode.
        assert no_bind_settle == [_BIND_SETTLE_SECONDS] * 2

    async def test_an_engine_that_never_becomes_ready_is_terminated_and_the_next_port_tried(
        self, mock_poll: AsyncMock, monkeypatch: pytest.MonkeyPatch, no_bind_settle: list[float]
    ) -> None:
        stuck = FakeProcess()
        spawner = _spawn(monkeypatch, [stuck, FakeProcess()])
        mock_poll.side_effect = [RuntimeError("no endpoint"), "ws://ready"]

        url = await crawl_obscura.ensure_crawl_obscura()

        assert url == f"http://127.0.0.1:{_BASE_PORT + 1}"
        assert spawner.ports == [_BASE_PORT, _BASE_PORT + 1]
        # The half-started engine must not be left running on the port it took.
        assert stuck.terminated is True

    async def test_exhausting_every_port_raises_naming_the_range(
        self, mock_poll: AsyncMock, monkeypatch: pytest.MonkeyPatch, no_bind_settle: list[float]
    ) -> None:
        attempts = _PORT_ATTEMPTS
        spawner = _spawn(monkeypatch, [FakeProcess() for _ in range(attempts + 1)])
        last_error = RuntimeError("no endpoint on the last port")
        mock_poll.side_effect = [RuntimeError("nope")] * (attempts - 1) + [last_error]

        with pytest.raises(RuntimeError) as exc_info:
            await crawl_obscura.ensure_crawl_obscura()

        assert str(exc_info.value) == (
            f"crawl Obscura could not bind a port in {_BASE_PORT}..{_BASE_PORT + attempts - 1}"
        )
        assert exc_info.value.__cause__ is last_error
        assert spawner.ports == list(range(_BASE_PORT, _BASE_PORT + attempts))

    async def test_a_failed_launch_leaves_no_engine_behind_for_the_next_caller(
        self, mock_poll: AsyncMock, monkeypatch: pytest.MonkeyPatch, no_bind_settle: list[float]
    ) -> None:
        attempts = _PORT_ATTEMPTS
        spawner = _spawn(monkeypatch, [FakeProcess() for _ in range(attempts + 1)])
        mock_poll.side_effect = [RuntimeError("nope")] * attempts + ["ws://ready"]

        with pytest.raises(RuntimeError):
            await crawl_obscura.ensure_crawl_obscura()
        url = await crawl_obscura.ensure_crawl_obscura()

        assert url == f"http://127.0.0.1:{_BASE_PORT}"
        assert len(spawner.ports) == attempts + 1

    async def test_every_port_taken_raises_with_no_underlying_error(
        self, mock_poll: AsyncMock, monkeypatch: pytest.MonkeyPatch, no_bind_settle: list[float]
    ) -> None:
        """Nothing failed on the way — every port was simply occupied."""
        attempts = _PORT_ATTEMPTS
        _spawn(monkeypatch, [FakeProcess(returncode=1) for _ in range(attempts)])

        with pytest.raises(RuntimeError) as exc_info:
            await crawl_obscura.ensure_crawl_obscura()

        assert exc_info.value.__cause__ is None
        mock_poll.assert_not_awaited()

    async def test_the_engines_own_output_is_discarded(
        self, mock_poll: AsyncMock, monkeypatch: pytest.MonkeyPatch, no_bind_settle: list[float]
    ) -> None:
        """Obscura is chatty; its pipes must not land in the API's own streams."""
        spawner = _spawn(monkeypatch, [FakeProcess()])

        await crawl_obscura.ensure_crawl_obscura()

        assert spawner.kwargs == [
            {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL},
        ]

    async def test_a_process_that_dies_before_termination_does_not_break_the_probe(
        self, mock_poll: AsyncMock, monkeypatch: pytest.MonkeyPatch, no_bind_settle: list[float]
    ) -> None:
        """The engine can exit between the returncode check and terminate(); that is not an error."""
        vanishing = FakeProcess(terminate_error=ProcessLookupError)
        spawner = _spawn(monkeypatch, [vanishing, FakeProcess()])
        mock_poll.side_effect = [RuntimeError("no endpoint"), "ws://ready"]

        url = await crawl_obscura.ensure_crawl_obscura()

        assert url == f"http://127.0.0.1:{_BASE_PORT + 1}"
        assert spawner.ports == [_BASE_PORT, _BASE_PORT + 1]

    async def test_a_process_that_ignores_termination_does_not_wedge_the_probe(
        self, mock_poll: AsyncMock, monkeypatch: pytest.MonkeyPatch, no_bind_settle: list[float]
    ) -> None:
        """A half-started engine that never reaps must not stop us trying the next port."""
        unreapable = FakeProcess(wait_error=TimeoutError)
        spawner = _spawn(monkeypatch, [unreapable, FakeProcess()])
        mock_poll.side_effect = [RuntimeError("no endpoint"), "ws://ready"]

        url = await crawl_obscura.ensure_crawl_obscura()

        assert url == f"http://127.0.0.1:{_BASE_PORT + 1}"
        assert spawner.ports == [_BASE_PORT, _BASE_PORT + 1]

    async def test_a_terminated_engine_gets_two_seconds_to_go(
        self, mock_poll: AsyncMock, monkeypatch: pytest.MonkeyPatch, no_bind_settle: list[float]
    ) -> None:
        _spawn(monkeypatch, [FakeProcess(), FakeProcess()])
        mock_poll.side_effect = [RuntimeError("no endpoint"), "ws://ready"]
        recorded = _record_wait_for_timeouts(monkeypatch)

        await crawl_obscura.ensure_crawl_obscura()

        # Shorter than the shutdown grace: this reap is on the hot path of a
        # crawl that is still waiting for an engine.
        assert recorded == [2]


class TestShutdownCrawlObscura:
    """Teardown: terminate, five-second grace, then kill — and always forget the engine."""

    async def test_terminates_the_running_engine_and_forgets_it(
        self, monkeypatch: pytest.MonkeyPatch, no_bind_settle: list[float]
    ) -> None:
        running = FakeProcess()
        _running(monkeypatch, running)
        spawner = _spawn(monkeypatch, [FakeProcess()])

        await crawl_obscura.shutdown_crawl_obscura()

        assert running.terminated is True
        assert running.waited is True
        assert running.killed is False
        # Forgotten: the next caller launches a fresh engine rather than handing
        # out the terminated one's URL.
        with patch("app.utils.crawl_obscura.poll_obscura_endpoint", new_callable=AsyncMock):
            await crawl_obscura.ensure_crawl_obscura()
        assert spawner.ports == [_BASE_PORT]

    async def test_the_engine_gets_five_seconds_to_exit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _running(monkeypatch, FakeProcess())
        recorded = _record_wait_for_timeouts(monkeypatch)

        await crawl_obscura.shutdown_crawl_obscura()

        assert recorded == [5]

    async def test_an_engine_that_will_not_exit_is_killed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stuck = FakeProcess(wait_error=TimeoutError)
        _running(monkeypatch, stuck)

        await crawl_obscura.shutdown_crawl_obscura()

        assert stuck.killed is True

    async def test_an_already_exited_engine_is_left_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exited = FakeProcess(returncode=0)
        _running(monkeypatch, exited)

        await crawl_obscura.shutdown_crawl_obscura()

        assert exited.terminated is False
        assert exited.waited is False
        assert exited.killed is False

    async def test_shutting_down_without_a_launch_is_a_no_op(self) -> None:
        await crawl_obscura.shutdown_crawl_obscura()

        assert crawl_obscura._engine is None
