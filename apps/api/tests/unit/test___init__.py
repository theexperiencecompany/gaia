"""Browser-Use's calls home stay off in every GAIA process, whatever the environment says."""

from pathlib import Path
import subprocess
import sys

_API_ROOT = Path(__file__).resolve().parents[2]
_PROBE = (
    "import app\n"
    "from browser_use.config import CONFIG\n"
    "print(CONFIG.ANONYMIZED_TELEMETRY, CONFIG.BROWSER_USE_VERSION_CHECK, CONFIG.BROWSER_USE_CLOUD_SYNC)"
)


def test_telemetry_and_the_version_check_are_off_before_browser_use_loads() -> None:
    """Each run paid a PyPI request (up to 3 s) and sent usage to Browser-Use's PostHog."""
    env = {"PATH": "", "ANONYMIZED_TELEMETRY": "true", "BROWSER_USE_VERSION_CHECK": "true"}

    probe = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=_API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert probe.stdout.split() == ["False", "False", "False"]


_BUDGET_PROBE = (
    "import app\n"
    "from browser_use.browser.events import BrowserStateRequestEvent, ScreenshotEvent\n"
    "print(ScreenshotEvent().event_timeout, BrowserStateRequestEvent().event_timeout)"
)


def _budgets(env: dict[str, str]) -> list[float]:
    probe = subprocess.run(
        [sys.executable, "-c", _BUDGET_PROBE],
        cwd=_API_ROOT,
        env={"PATH": "", **env},
        capture_output=True,
        text=True,
        check=True,
    )
    return [float(budget) for budget in probe.stdout.split()]


def test_a_screenshot_outlasts_the_slowest_measured_and_the_state_read_outlasts_it() -> None:
    """A first Obscura capture of a long page took up to 35 s, past Browser-Use's own 15 s."""
    screenshot, state_read = _budgets({})

    assert screenshot > 35
    assert state_read > screenshot


def test_an_operators_own_budget_wins() -> None:
    assert _budgets({"TIMEOUT_ScreenshotEvent": "5", "TIMEOUT_BrowserStateRequestEvent": "7"}) == [
        5.0,
        7.0,
    ]
