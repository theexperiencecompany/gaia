"""Sidecar workers run beside the main one, stop with it, and take the process down if one dies."""

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.workers import sidecar_worker as sidecar_mod

pytestmark = pytest.mark.unit


class _FakeWorker:
    """Stands in for arq's Worker: runs until closed, or dies when told to."""

    def __init__(self, dies_with: Exception | None = None) -> None:
        self.dies_with = dies_with
        self.closed = False
        self._stop = asyncio.Event()

    async def async_run(self) -> None:
        if self.dies_with is not None:
            raise self.dies_with
        await self._stop.wait()
        raise asyncio.CancelledError

    async def close(self) -> None:
        self.closed = True
        self._stop.set()


@pytest.fixture
def raised_signals(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    raise_signal = MagicMock()
    monkeypatch.setattr(sidecar_mod.signal, "raise_signal", raise_signal)
    return raise_signal


async def test_every_sidecar_worker_runs_beside_the_main_one_and_stops_with_it(
    raised_signals: MagicMock,
) -> None:
    first, second = _FakeWorker(), _FakeWorker()
    ctx: dict[str, Any] = {}

    sidecar_mod.start_sidecar_worker(ctx, "first", first)  # type: ignore[arg-type]  # a stand-in for arq's Worker
    sidecar_mod.start_sidecar_worker(ctx, "second", second)  # type: ignore[arg-type]  # a stand-in for arq's Worker
    await asyncio.sleep(0)
    await sidecar_mod.stop_sidecar_workers(ctx)

    assert first.closed
    assert second.closed
    raised_signals.assert_not_called()


async def test_a_sidecar_worker_that_dies_takes_the_process_down_to_be_restarted(
    raised_signals: MagicMock,
) -> None:
    ctx: dict[str, Any] = {}

    sidecar_mod.start_sidecar_worker(
        ctx,
        "dying",
        _FakeWorker(dies_with=ConnectionError("redis went away")),  # type: ignore[arg-type]  # a stand-in for arq's Worker
    )
    for _ in range(3):
        await asyncio.sleep(0)

    raised_signals.assert_called_once_with(sidecar_mod.signal.SIGTERM)
    await sidecar_mod.stop_sidecar_workers(ctx)


async def test_a_dying_sidecar_worker_says_which_one_took_the_process_down(
    monkeypatch: pytest.MonkeyPatch, raised_signals: MagicMock
) -> None:
    fake_log = MagicMock()
    monkeypatch.setattr(sidecar_mod, "log", fake_log)
    task = MagicMock(cancelled=MagicMock(return_value=False))
    task.get_name.return_value = "outbox_worker"

    sidecar_mod._stop_process_if_it_ended(task)

    (message,), kwargs = fake_log.error.call_args
    assert "Sidecar worker stopped" in message
    assert kwargs["sidecar"] == "outbox_worker"


async def test_a_sidecar_workers_task_is_named_for_it(raised_signals: MagicMock) -> None:
    """The name is what a stuck-task dump or an unobserved failure reports it by."""
    ctx: dict[str, Any] = {}

    sidecar_mod.start_sidecar_worker(ctx, "outbox_worker", _FakeWorker())  # type: ignore[arg-type]  # a stand-in for arq's Worker
    try:
        [running] = ctx[sidecar_mod.SIDECAR_WORKERS_CTX_KEY]
        assert running.task.get_name() == "outbox_worker"
    finally:
        await sidecar_mod.stop_sidecar_workers(ctx)


async def test_shutdown_after_a_startup_that_never_started_one_is_a_no_op() -> None:
    await sidecar_mod.stop_sidecar_workers({})
