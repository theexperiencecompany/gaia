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
import sys

CI = Path(__file__).parent.parent


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    """Return a git repo holding pytest.sh, its libs and one committed test file."""
    root = tmp_path / "repo"
    scripts = root / "scripts" / "ci"
    (scripts / "lib").mkdir(parents=True)
    for name in ("pytest.sh", "verdict.py", "lib/github.py", "lib/log.sh", "lib/cpu-slots.sh"):
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


# --- slice: nothing an earlier job left behind is ever read -----------------

# `uv run --no-project verdict.py …` runs the real verdict under this test's
# interpreter (it carries defusedxml, as uv's inline-script env does); `uv run
# --frozen pytest …` dies before writing its JUnit, the case a stale report hides.
UV_STUB = f"""\
#!/usr/bin/env bash
if [ "$2" = "--no-project" ]; then shift 2; exec {sys.executable} "$@"; fi
exit 2
"""

STDBUF_STUB = """\
#!/usr/bin/env bash
shift
exec "$@"
"""

STALE_JUNIT = """\
<testsuites><testsuite name="pytest" tests="1" failures="1">
<testcase classname="tests.test_other_pr" name="test_from_another_job"
 file="tests/test_other_pr.py" line="3"><failure message="boom">boom</failure></testcase>
</testsuite></testsuites>
"""


def _run_slice(tmp_path: Path, root: Path) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("uv", UV_STUB), ("stdbuf", STDBUF_STUB)):
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(0o755)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k != "RUNNER_ENVIRONMENT"}
    env.update(
        PATH=f"{bin_dir}:{env['PATH']}",
        RUNNER_TEMP=str(runner_temp),
        SLICE_NAME="unit-a",
        SLICE_PATHS="tests/unit",
        XDIST_N="2",
    )
    return subprocess.run(
        ["bash", str(root / "scripts" / "ci" / "pytest.sh"), "slice"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _repo_with_selector(tmp_path: Path) -> Path:
    root = _repo(tmp_path)
    shutil.copy(CI / "test_impact.py", root / "scripts" / "ci" / "test_impact.py")
    return root


def test_slice_ignores_a_selection_an_earlier_job_left_in_the_workspace(tmp_path: Path) -> None:
    """A PR job's selection in the persistent checkout must not narrow a later master run."""
    root = _repo_with_selector(tmp_path)
    stale = root / "apps" / "api" / ".test-impact" / "selected-unit-a.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("tests/test_other_pr.py::test_from_another_job\n")

    result = _run_slice(tmp_path, root)

    assert "running ALL" in result.stdout, result.stdout + result.stderr
    assert "selected targets" not in result.stdout


def test_slice_reads_the_selection_this_job_wrote(tmp_path: Path) -> None:
    root = _repo_with_selector(tmp_path)
    mine = tmp_path / "runner-temp" / "test-impact" / "selected-unit-a.txt"
    mine.parent.mkdir(parents=True)
    mine.write_text("tests/test_x.py::test_x\n")

    result = _run_slice(tmp_path, root)

    assert "running 1 selected targets" in result.stdout, result.stdout + result.stderr


def test_slice_never_reports_from_an_earlier_jobs_junit(tmp_path: Path) -> None:
    """Pytest died before writing a report; the verdict must not borrow someone else's."""
    root = _repo_with_selector(tmp_path)
    for stale in (
        root / "apps" / "api" / "test-results" / "pytest-unit-a.xml",
        tmp_path / "runner-temp" / "pytest-unit-a.xml",
    ):
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text(STALE_JUNIT)

    result = _run_slice(tmp_path, root)

    assert result.returncode != 0
    verdict = _verdicts(tmp_path)["test-python/unit-a"]
    assert "test_from_another_job" not in json.dumps(verdict), verdict
    assert verdict["status"] == "error"


# --- flake-gate: the rerun replays this run's failures, nobody else's ---------

# Records each invocation's argv, one file per call; the first call fails.
FAKE_PYTEST = """\
#!/usr/bin/env bash
n=$(ls "$REC"/call-* 2>/dev/null | wc -l | tr -d ' ')
printf '%s\\n' "$@" > "$REC/call-$n"
[ "$n" -gt 0 ]
"""


def _cache_dir_of(call: Path) -> str:
    args = call.read_text().splitlines()
    overrides = [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == "-o"]
    dirs = [o.removeprefix("cache_dir=") for o in overrides if o.startswith("cache_dir=")]
    assert len(dirs) == 1, f"no single cache_dir override in {args}"
    return dirs[0]


def test_flake_gate_reruns_from_a_cache_only_this_run_wrote(tmp_path: Path) -> None:
    """`--lf` against the workspace's shared .pytest_cache replays an earlier job's failures."""
    workspace = tmp_path / "workspace"
    (workspace / ".pytest_cache").mkdir(parents=True)
    fake = tmp_path / "fake-pytest"
    fake.write_text(FAKE_PYTEST)
    fake.chmod(0o755)

    result = subprocess.run(
        ["bash", str(CI / "pytest.sh"), "flake-gate", str(fake), "tests"],
        cwd=workspace,
        env={**os.environ, "REC": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 1
    assert "FLAKY TESTS DETECTED" in result.stderr
    first, rerun = _cache_dir_of(tmp_path / "call-0"), _cache_dir_of(tmp_path / "call-1")
    assert first == rerun
    assert "--lf" in (tmp_path / "call-1").read_text().splitlines()
    assert not Path(first).is_relative_to(workspace)
    assert not Path(first).exists(), "the job-local cache outlived the gate"
