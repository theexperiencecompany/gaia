"""The real-services gate: run against live Mongo + Redis, fail loud when opted in but unreachable, else skip once."""

from __future__ import annotations

from collections.abc import Iterator
import socket

import pytest

pytest_plugins = ["pytester"]

_SUITE = """
import pytest

@pytest.mark.real_services
def test_reads_mongo():
    pass

@pytest.mark.real_services
def test_reads_redis():
    pass

def test_hermetic():
    pass
"""


@pytest.fixture(autouse=True)
def _no_plugin_autoload(monkeypatch: pytest.MonkeyPatch) -> None:
    # The inner run reads no pytest.ini, so it would import every installed plugin (opik ~4s).
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")


@pytest.fixture
def listening_port() -> Iterator[int]:
    with socket.create_server(("127.0.0.1", 0)) as server:
        yield server.getsockname()[1]


@pytest.fixture
def closed_port() -> int:
    with socket.create_server(("127.0.0.1", 0)) as server:
        return int(server.getsockname()[1])


def _run(pytester: pytest.Pytester) -> pytest.RunResult:
    pytester.makepyfile(test_suite=_SUITE)
    return pytester.runpytest("-p", "tests.real_services", "-q")


def test_opted_in_with_mongo_unreachable_fails_naming_the_service(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    listening_port: int,
    closed_port: int,
) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("USE_REAL_SERVICES", "1")
    monkeypatch.setenv("MONGO_DB", f"mongodb://user:secret@127.0.0.1:{closed_port}/gaia_test")
    monkeypatch.setenv("REDIS_URL", f"redis://127.0.0.1:{listening_port}/0")

    result = _run(pytester)

    result.assert_outcomes(passed=1, errors=2)
    output = result.stdout.str()
    assert f"Mongo at 127.0.0.1:{closed_port} (MONGO_DB) is unreachable" in output
    assert "Redis at" not in output
    assert "secret" not in output


def test_opted_in_with_both_services_up_runs_the_tier(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, listening_port: int
) -> None:
    monkeypatch.setenv("USE_REAL_SERVICES", "1")
    monkeypatch.setenv("MONGO_DB", f"mongodb://127.0.0.1:{listening_port}/gaia_test")
    monkeypatch.setenv("REDIS_URL", f"redis://127.0.0.1:{listening_port}/0")

    _run(pytester).assert_outcomes(passed=3)


def test_not_opted_in_skips_with_one_summary_line(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("USE_REAL_SERVICES", raising=False)

    result = _run(pytester)

    result.assert_outcomes(passed=1, skipped=2)
    summary = [line for line in result.outlines if "real-services tests skipped" in line]
    assert summary == [
        "2 real-services tests skipped: USE_REAL_SERVICES is unset. Run `mise run "
        "test:python:real`, or set USE_REAL_SERVICES=1 with Mongo + Redis up."
    ]
