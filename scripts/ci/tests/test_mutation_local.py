"""`mutation.py local` refuses to start while another local run owns this checkout's logs.

Each local run clears verify-logs/mutation before it starts. A second run started
beside the first wiped the first's module logs and verdict records mid-run, and the
first then crashed reading a module output that no longer existed.
"""

from __future__ import annotations

import fcntl
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MUTATION_PY = REPO_ROOT / "scripts" / "ci" / "mutation.py"
LOCAL_LOG_DIR = REPO_ROOT / "verify-logs" / "mutation"
LOCK = REPO_ROOT / "verify-logs" / "mutation.lock"


def test_a_second_local_run_leaves_the_running_ones_logs_alone() -> None:
    LOCAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    running_log = LOCAL_LOG_DIR / "test_mutation_local.sentinel.log"
    running_log.write_text("a module the first run is still mutating\n")
    try:
        with LOCK.open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            second = subprocess.run(
                [sys.executable, str(MUTATION_PY), "local", "app/does_not_exist.py"],
                capture_output=True,
                text=True,
                check=False,
                cwd=REPO_ROOT,
            )
        assert second.returncode == 2, second.stdout + second.stderr
        assert "another `mutation.py local` run" in second.stderr
        assert running_log.read_text() == "a module the first run is still mutating\n"
    finally:
        running_log.unlink(missing_ok=True)


@pytest.mark.parametrize(
    "path",
    [
        "scripts/provision_inbox_desks.py",
        "apps/api/scripts/provision_inbox_desks.py",
        "app/main.py",
        "app/services/__init__.py",
    ],
)
def test_a_module_ci_never_mutates_is_refused_before_anything_runs(path: str) -> None:
    LOCAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    earlier_log = LOCAL_LOG_DIR / "test_mutation_local.earlier.log"
    earlier_log.write_text("an earlier run's log\n")
    try:
        refused = subprocess.run(
            [sys.executable, str(MUTATION_PY), "local", path],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO_ROOT,
        )
        assert refused.returncode == 2, refused.stdout + refused.stderr
        assert f"apps/api/{path.removeprefix('apps/api/')}" in refused.stderr
        assert "CI only mutates modules under apps/api/app/" in refused.stderr
        assert "has no test file" not in refused.stdout + refused.stderr
        assert earlier_log.read_text() == "an earlier run's log\n"
    finally:
        earlier_log.unlink(missing_ok=True)
