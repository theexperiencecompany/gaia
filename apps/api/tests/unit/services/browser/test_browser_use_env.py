"""Browser-Use's calls home stay off in every GAIA process, whatever the environment says."""

from pathlib import Path
import subprocess
import sys

_API_ROOT = Path(__file__).resolve().parents[4]
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
