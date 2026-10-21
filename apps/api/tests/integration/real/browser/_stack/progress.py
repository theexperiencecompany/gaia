"""The stack's progress, written past pytest's output capture so a slow or stuck run says where it is.

Under xdist a worker's stdout is its channel to the controller, but its stderr is
the controller's own, so these lines reach the CI log as they happen, one per
boot phase and per scenario, each with the worker, the time and the seconds since
the stack started.
"""

from __future__ import annotations

import os
import sys
import time

import pytest


class Progress:
    """One stack's timestamped progress lines."""

    def __init__(self, config: pytest.Config) -> None:
        self._config = config
        self._worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
        self._started = time.monotonic()

    def say(self, what: str) -> None:
        elapsed = time.monotonic() - self._started
        line = (
            f"[browser stack {self._worker} {time.strftime('%H:%M:%S')} +{elapsed:.0f}s] {what}\n"
        )
        capture = self._config.pluginmanager.getplugin("capturemanager")
        if capture is None:
            sys.stderr.write(line)
            sys.stderr.flush()
            return
        with capture.global_and_fixture_disabled():
            sys.stderr.write(line)
            sys.stderr.flush()
