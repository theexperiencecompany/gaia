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

import pytest
from sandbox import VERDICT_FILES

CI = Path(__file__).parent.parent


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    """Return a git repo holding pytest.sh, its libs and one committed test file."""
    root = tmp_path / "repo"
    scripts = root / "scripts" / "ci"
    (scripts / "lib").mkdir(parents=True)
    for name in (
        "pytest.sh",
        *VERDICT_FILES,
        "lib/log.sh",
        "lib/cpu-slots.sh",
        "lib/runner-host.sh",
    ):
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


def _run_slice(
    tmp_path: Path, root: Path, uv_stub: str = UV_STUB, **extra_env: str
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("uv", uv_stub), ("stdbuf", STDBUF_STUB)):
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(0o755)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k != "RUNNER_NAME"}
    env.update(
        PATH=f"{bin_dir}:{env['PATH']}",
        RUNNER_TEMP=str(runner_temp),
        SLICE_NAME="unit-a",
        SLICE_PATHS="tests/unit",
        XDIST_N="2",
        **extra_env,
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


# Records the suite's argv instead of running it.
RECORDING_UV_STUB = f"""\
#!/usr/bin/env bash
if [ "$2" = "--no-project" ]; then shift 2; exec {sys.executable} "$@"; fi
printf '%s\\n' "$@" > "$REC/suite-argv"
exit 2
"""


def _suite_argv(tmp_path: Path, sha: str) -> list[str]:
    rec = tmp_path / f"rec-{sha}"
    rec.mkdir()
    _run_slice(
        tmp_path,
        _repo_with_selector(tmp_path / sha),
        RECORDING_UV_STUB,
        REC=str(rec),
        GITHUB_SHA=sha,
    )
    return (rec / "suite-argv").read_text().splitlines()


def _suite_seed(tmp_path: Path, sha: str) -> list[str]:
    return [a for a in _suite_argv(tmp_path, sha) if a.startswith("--randomly-seed")]


GNU_TIME = (
    subprocess.run(["/usr/bin/time", "-v", "true"], capture_output=True, check=False).returncode
    == 0
)


@pytest.mark.skipif(
    not GNU_TIME, reason="the slice runs pytest under GNU time -v, as CI's Linux runners have"
)
def test_the_test_order_is_seeded_by_the_commit(tmp_path: Path) -> None:
    """Unseeded, pytest-randomly shuffled every run, so a commit's order-dependent failure came and went."""
    sha = "0a1b2c3d" + "0" * 32
    assert _suite_seed(tmp_path, sha) == [f"--randomly-seed={int(sha[:8], 16)}"]
    assert _suite_seed(tmp_path, "f" * 40) == [f"--randomly-seed={int('f' * 8, 16)}"]


# --- flake-gate: pytest-rerunfailures reruns a failure once, in its worker ----

# Fails on its first run in a fresh directory and passes on the rerun: a flake.
FLAKY_TEST = """\
from pathlib import Path


def test_flaky(tmp_path_factory):
    marker = Path(__file__).with_suffix(".ran")
    if not marker.exists():
        marker.write_text("1")
        raise AssertionError("first run")
"""


def _flake_gate_on(tmp_path: Path, test_body: str, event: str) -> subprocess.CompletedProcess[str]:
    tests = tmp_path / "suite"
    tests.mkdir()
    (tests / "test_it.py").write_text(test_body)
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_EVENT_NAME"}
    if event:
        env["GITHUB_EVENT_NAME"] = event
    return subprocess.run(
        [
            "bash",
            str(CI / "pytest.sh"),
            "flake-gate",
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            str(tests),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize(
    ("event", "expected"),
    [("pull_request", 1), ("workflow_dispatch", 1), ("", 1), ("merge_group", 0), ("push", 0)],
)
def test_a_test_that_passes_only_on_its_rerun_fails_the_lane_on_a_pr(
    tmp_path: Path, event: str, expected: int
) -> None:
    """The queue and master must not eject on a flake; a PR push, with a human there, still fails it."""
    result = _flake_gate_on(tmp_path, FLAKY_TEST, event)
    assert result.returncode == expected, result.stdout + result.stderr
    assert "FLAKY" in result.stderr


def test_a_test_that_fails_twice_is_a_genuine_failure(tmp_path: Path) -> None:
    result = _flake_gate_on(tmp_path, "def test_broken():\n    assert False\n", "merge_group")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FLAKY" not in result.stderr


def test_regression_proof_proves_a_module_marked_through_pytestmark(tmp_path: Path) -> None:
    """The lane's own advice names pytestmark, yet a decorator grep skipped such a file."""
    root = _repo(tmp_path)
    (root / "apps" / "api" / "tests" / "test_pinned.py").write_text(
        "import pytest\n\npytestmark = pytest.mark.regression\n\n\ndef test_bug():\n    assert True\n"
    )
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "pin")
    subprocess.run(
        ["bash", str(root / "scripts" / "ci" / "pytest.sh"), "regression-proof", "HEAD~1"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    # The fixture has no API venv, so the run stops after selection; what matters is that it got there.
    verdict = _verdicts(tmp_path).get("regression-proof", {})
    assert verdict.get("status") != "skip", verdict


def _flake_gate_on_exit(tmp_path: Path, code: int, **env: str) -> int:
    fake = tmp_path / "fake-pytest"
    fake.write_text(f"#!/usr/bin/env bash\nexit {code}\n")
    fake.chmod(0o755)
    return subprocess.run(
        ["bash", str(CI / "pytest.sh"), "flake-gate", str(fake)],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    ).returncode


def test_flake_gate_fails_a_full_run_that_collected_nothing(tmp_path: Path) -> None:
    """A whole slice or -m schemathesis collecting nothing is a broken path or marker, not a pass."""
    assert _flake_gate_on_exit(tmp_path, 5) != 0


def test_flake_gate_passes_a_selection_the_markers_deselected(tmp_path: Path) -> None:
    assert _flake_gate_on_exit(tmp_path, 5, FLAKE_GATE_SELECTION="1") == 0


@pytest.mark.skipif(
    not GNU_TIME, reason="the slice runs pytest under GNU time -v, as CI's Linux runners have"
)
def test_the_slice_takes_its_markers_and_timeout_from_pytest_ini(tmp_path: Path) -> None:
    """It overrode addopts and restated -m and --timeout, a second copy pytest.ini could drift from."""
    argv = _suite_argv(tmp_path, "c" * 40)
    assert not [a for a in argv if a.startswith(("--override-ini", "--timeout")) or a == "-m"], argv
