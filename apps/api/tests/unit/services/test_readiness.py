"""Readiness aggregation: every dependency answers for itself, and none can stall the probe."""

import asyncio

import pytest

from app.services import readiness


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
