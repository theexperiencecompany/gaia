"""The one real-services gate, loaded by the root conftest.

A test marked real_services runs when USE_REAL_SERVICES=1 and Mongo + Redis answer,
fails at setup naming the dead service when opted in but unreachable, and otherwise
skips, with a single terminal-summary line saying why.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import os
import socket
from urllib.parse import urlsplit

import pytest

REAL_SERVICES_MARK = "real_services"
_OPT_IN = "USE_REAL_SERVICES"
_SKIP_REASON = f"requires {_OPT_IN}=1 with real Mongo + Redis up"
_PROBE_TIMEOUT_SECONDS = 2.0
_SERVICES = (("Mongo", "MONGO_DB", 27017), ("Redis", "REDIS_URL", 6379))
_PROBE_RESULT = pytest.StashKey[str | None]()


def mark_real_services(items: Iterable[pytest.Item]) -> None:
    """Put the items behind the real-services gate."""
    for item in items:
        item.add_marker(REAL_SERVICES_MARK)


def unreachable_services(env: Mapping[str, str]) -> str | None:
    """Return each service that refuses a TCP connect, as host:port (never credentials); None when all answer."""
    problems: list[str] = []
    for service, var, default_port in _SERVICES:
        url = env.get(var, "")
        if not url:
            problems.append(f"{service} has no URL ({var} is unset)")
            continue
        parts = urlsplit(url)
        address = (parts.hostname or "localhost", parts.port or default_port)
        try:
            socket.create_connection(address, timeout=_PROBE_TIMEOUT_SECONDS).close()
        except OSError as exc:
            problems.append(f"{service} at {address[0]}:{address[1]} ({var}) is unreachable: {exc}")
    return "; ".join(problems) or None


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker(REAL_SERVICES_MARK) is None:
        return
    if os.environ.get(_OPT_IN, "0") != "1":
        pytest.skip(_SKIP_REASON)
    stash = item.config.stash
    if _PROBE_RESULT not in stash:
        stash[_PROBE_RESULT] = unreachable_services(os.environ)
    problem = stash[_PROBE_RESULT]
    if problem:
        pytest.fail(
            f"{_OPT_IN}=1 but {problem}. Start the services, or unset {_OPT_IN} to skip this tier.",
            pytrace=False,
        )


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    # -q prints only "N skipped", so without this line the reason is invisible.
    skipped = [
        report
        for report in terminalreporter.stats.get("skipped", [])
        if isinstance(report.longrepr, tuple) and report.longrepr[2] == f"Skipped: {_SKIP_REASON}"
    ]
    if skipped:
        terminalreporter.write_line(
            f"{len(skipped)} real-services tests skipped: {_OPT_IN} is unset. Run `mise run "
            f"test:python:real`, or set {_OPT_IN}=1 with Mongo + Redis up.",
            yellow=True,
        )
