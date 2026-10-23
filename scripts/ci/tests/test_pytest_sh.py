"""pytest.sh: the Python suite's runner never reads a missing answer as a pass.

Driven as the real script, copied into a throwaway git repo beside the libs it
sources, with the externals it shells out to (uv, stdbuf) replaced by fakes on
PATH. Each test names a defect that let a lane go green on a check it never
ran.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

CI = Path(__file__).parent.parent


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    """Return a git repo holding pytest.sh, its libs and one committed test file."""
    root = tmp_path / "repo"
    scripts = root / "scripts" / "ci"
    (scripts / "lib").mkdir(parents=True)
    for name in ("pytest.sh", "verdict.py", "lib/log.sh", "lib/cpu-slots.sh"):
        shutil.copy(CI / name, scripts / name)
    tests = root / "apps" / "api" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_x.py").write_text("def test_x():\n    assert True\n")
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
    return root


def _verdicts(tmp_path: Path) -> dict[str, dict[str, object]]:
    root = Path(os.environ["GAIA_VERDICT_DIR"])
    return {
        str(doc["lane"]): doc for doc in (json.loads(p.read_text()) for p in root.rglob("*.json"))
    }


def test_regression_proof_fails_when_the_base_ref_does_not_resolve(tmp_path: Path) -> None:
    """A failed `git diff` is not "no changed tests"; reading it so skipped the lane green."""
    root = _repo(tmp_path)
    result = subprocess.run(
        ["bash", str(root / "scripts" / "ci" / "pytest.sh"), "regression-proof", "origin/nope"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "regression-proof" not in _verdicts(tmp_path)


def test_regression_proof_skips_a_diff_with_no_changed_tests(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = subprocess.run(
        ["bash", str(root / "scripts" / "ci" / "pytest.sh"), "regression-proof", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _verdicts(tmp_path)["regression-proof"]["status"] == "skip"
