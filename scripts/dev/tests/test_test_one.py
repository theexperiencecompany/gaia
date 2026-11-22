"""`mise test:one` resolves each path from the directory it was run in, then runs pytest from apps/api."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "dev" / "test-one.sh"
API_DIR = REPO_ROOT / "apps" / "api"
PYTEST_PREFIX = ["run", "--group", "backend", "--group", "dev", "pytest", "-p", "no:xdist", "-q"]


def run_test_one(
    caller_dir: Path, args: list[str], tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, list[str]]:
    """Run the script with a uv that records its cwd and argv; return both."""
    bin_dir = tmp_path_factory.mktemp("bin")
    log = bin_dir / "uv.log"
    uv = bin_dir / "uv"
    uv.write_text(f'#!/bin/sh\npwd > {log}\nfor a in "$@"; do echo "$a" >> {log}; done\n')
    uv.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "MISE_ORIGINAL_CWD": str(caller_dir),
    }
    subprocess.run(["bash", str(SCRIPT), *args], cwd=REPO_ROOT, env=env, check=True)
    cwd, *argv = log.read_text().splitlines()
    return Path(cwd), argv


@pytest.mark.parametrize(
    ("caller_dir", "arg", "resolved"),
    [
        (
            REPO_ROOT,
            "scripts/dev/tests/test_test_one.py",
            REPO_ROOT / "scripts/dev/tests/test_test_one.py",
        ),
        (REPO_ROOT, "apps/api/tests/conftest.py", API_DIR / "tests/conftest.py"),
        (API_DIR, "tests/conftest.py", API_DIR / "tests/conftest.py"),
        (API_DIR, "../../scripts/dev/tests", API_DIR / "../../scripts/dev/tests"),
    ],
    ids=["root-scripts", "root-api", "api-tests", "api-dotdot"],
)
def test_a_path_is_resolved_from_the_callers_directory(
    caller_dir: Path, arg: str, resolved: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    cwd, argv = run_test_one(caller_dir, [arg], tmp_path_factory)
    assert cwd == API_DIR
    assert argv == [*PYTEST_PREFIX, str(resolved)]


def test_a_node_id_keeps_its_test_name(tmp_path_factory: pytest.TempPathFactory) -> None:
    _, argv = run_test_one(REPO_ROOT, ["apps/api/tests/conftest.py::test_x"], tmp_path_factory)
    assert argv[-1] == f"{API_DIR / 'tests/conftest.py'}::test_x"


def test_flags_and_unresolvable_args_pass_through_unchanged(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    args = ["tests/conftest.py", "-k", "not slow", "/abs/missing.py"]
    _, argv = run_test_one(REPO_ROOT, args, tmp_path_factory)
    assert argv == [*PYTEST_PREFIX, *args]
