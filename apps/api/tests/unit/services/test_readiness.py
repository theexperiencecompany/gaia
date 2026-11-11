"""Readiness aggregation: every dependency answers for itself, and none can stall the probe."""

import asyncio
from types import SimpleNamespace

import pytest

from app.constants.log_tags import LogTag
from app.services import readiness
from tests.helpers import captured_wide_event


async def _answers() -> None:
    return None


async def _refuses() -> None:
    raise ConnectionRefusedError("connect to mongo:27017 refused — secret-host")


async def _hangs() -> None:
    await asyncio.sleep(60)


@pytest.fixture
def checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness, "READINESS_CHECK_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(
        readiness,
        "DEPENDENCY_CHECKS",
        {"postgres": _answers, "mongodb": _refuses, "redis": _hangs},
    )


async def test_each_dependency_reports_its_own_outcome(checks: None) -> None:
    result = await readiness.check_readiness()

    by_name = {d.name: d for d in result.dependencies}
    assert result.status == "not_ready"
    assert by_name["postgres"].ok is True
    assert by_name["mongodb"].error_type == "ConnectionRefusedError"
    assert by_name["redis"].error_type == "TimeoutError"


async def test_a_hung_dependency_is_cut_off_at_the_timeout(checks: None) -> None:
    started = asyncio.get_running_loop().time()

    await readiness.check_readiness()

    assert asyncio.get_running_loop().time() - started < 1


async def test_failures_expose_the_exception_type_never_its_message(checks: None) -> None:
    result = await readiness.check_readiness()

    assert "secret-host" not in result.model_dump_json()


async def test_all_answering_is_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness, "DEPENDENCY_CHECKS", {"postgres": _answers, "redis": _answers})

    result = await readiness.check_readiness()

    assert result.status == "ready"


def _clock(monkeypatch: pytest.MonkeyPatch, *readings: float) -> None:
    ticks = iter(readings)
    # Only readiness's clock: the event loop keeps reading the real one.
    monkeypatch.setattr(readiness, "time", SimpleNamespace(monotonic=lambda: next(ticks)))


@pytest.mark.parametrize(
    ("ping", "ok"), [(_answers, True), (_refuses, False)], ids=["answers", "refuses"]
)
async def test_latency_is_the_checks_own_wall_time_in_milliseconds(
    monkeypatch: pytest.MonkeyPatch, ping, ok: bool
) -> None:
    monkeypatch.setattr(readiness, "DEPENDENCY_CHECKS", {"mongodb": ping})
    _clock(monkeypatch, 10.0, 10.0123456)

    [status] = (await readiness.check_readiness()).dependencies

    assert (status.ok, status.latency_ms) == (ok, 12.35)


async def test_each_failure_is_warned_naming_its_dependency(checks: None) -> None:
    async with captured_wide_event() as event:
        await readiness.check_readiness()

    assert sorted(event["warnings"], key=lambda w: w["dependency"]) == [
        {
            "msg": f"{LogTag.STARTUP} Readiness check failed",
            "dependency": "mongodb",
            "error": "connect to mongo:27017 refused — secret-host",
            "error_type": "ConnectionRefusedError",
        },
        {
            "msg": f"{LogTag.STARTUP} Readiness check failed",
            "dependency": "redis",
            "error": "",
            "error_type": "TimeoutError",
        },
    ]
