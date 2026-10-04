"""main.yml must still run every Python suite that exists.

Two suites were dropped silently when the `test-python-coverage` job was
removed: `libs/shared/py/tests` and the schemathesis contract fuzz. Nothing
went red — the job that ran them simply stopped existing, and a suite that no
longer runs looks exactly like a suite with no failures.

That is the failure mode these tests exist to make impossible: a test file can
only stop running here by someone editing THIS file, which a reviewer sees.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
MAIN_YML = REPO_ROOT / ".github" / "workflows" / "main.yml"
SLICES_FILE = REPO_ROOT / "scripts" / "ci" / "lib" / "test-slices.json"
PYTEST_SH = REPO_ROOT / "scripts" / "ci" / "pytest.sh"
DAGGER_MODULE = REPO_ROOT / ".dagger" / "src" / "gaia_ci" / "main.py"


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(MAIN_YML.read_text())


@pytest.fixture(scope="module")
def test_python(workflow: dict[str, Any]) -> dict[str, Any]:
    return workflow["jobs"]["test-python"]


@pytest.fixture(scope="module")
def slices() -> list[dict[str, Any]]:
    return json.loads(SLICES_FILE.read_text())["slices"]


def _step_running(job: dict[str, Any], command: str) -> dict[str, Any]:
    (step,) = [s for s in job["steps"] if command in str(s.get("run", ""))]
    return step


def test_the_matrix_is_the_shared_slice_file(workflow: dict[str, Any]) -> None:
    # One definition, read by CI and by the Dagger harness alike: an inline
    # matrix is a second copy, and the local run drifts from it silently.
    matrix = workflow["jobs"]["test-python"]["strategy"]["matrix"]["slice"]
    assert matrix == "${{ fromJSON(needs.detect.outputs.python_slices) }}"
    detect = workflow["jobs"]["detect"]
    assert detect["outputs"]["python_slices"] == "${{ steps.slices.outputs.python_slices }}"
    step = next(s for s in detect["steps"] if s.get("id") == "slices")
    assert step["run"].startswith("bash scripts/ci/pytest.sh slices")


def test_pytest_sh_publishes_exactly_the_slice_file(slices: list[dict[str, Any]]) -> None:
    line = subprocess.run(
        ["bash", str(PYTEST_SH), "slices"], check=True, capture_output=True, text=True
    ).stdout.strip()
    key, _, payload = line.partition("=")
    assert key == "python_slices"
    assert json.loads(payload) == slices


def test_the_dagger_harness_runs_the_same_slices_through_the_same_script() -> None:
    module = DAGGER_MODULE.read_text()
    assert '"scripts/ci/lib/test-slices.json"' in module
    assert "bash /app/scripts/ci/pytest.sh {step}" in module


def test_the_gaia_shared_suite_still_runs(
    test_python: dict[str, Any], slices: list[dict[str, Any]]
) -> None:
    # gaia-shared is imported by the API; its tests had their own step in the
    # retired coverage job and went with it.
    step = _step_running(test_python, "pytest.sh shared-suite")
    assert step["if"] == "contains(matrix.slice.after, 'shared-suite')"
    assert any("shared-suite" in s["after"] for s in slices), "no slice runs the shared suite"
    assert "../../libs/shared/py/tests" in PYTEST_SH.read_text()


def test_gaia_shared_runs_in_its_own_pytest_invocation(test_python: dict[str, Any]) -> None:
    # NOT as a slice path. Handing pytest paths from two trees at once moves
    # rootdir to the repo root, apps/api/pytest.ini stops being the inifile,
    # and asyncio_mode/marker registration vanish — which killed the whole
    # slice (2145 failed, 891 errors) the one time it was tried.
    for entry in json.loads(SLICES_FILE.read_text())["slices"]:
        assert "libs/shared" not in entry["paths"], (
            f"slice {entry['name']} lists libs/shared in its paths; it needs its own run"
        )


def test_no_slice_reaches_outside_apps_api(slices: list[dict[str, Any]]) -> None:
    # The general form of the rule above: every slice path stays inside the
    # tree that owns pytest.ini, so rootdir is stable for every slice.
    for entry in slices:
        for path in entry["paths"].split():
            assert not path.startswith(".."), (
                f"slice {entry['name']}: {path} escapes apps/api and moves pytest's rootdir"
            )


def test_every_slice_path_exists(slices: list[dict[str, Any]]) -> None:
    # A path that no longer exists collects nothing; pytest errors on a bad
    # positional, but an --ignore'd or renamed tree can go quiet instead.
    api = REPO_ROOT / "apps" / "api"
    for entry in slices:
        for path in entry["paths"].split():
            assert (api / path).exists(), f"slice {entry['name']}: {path} does not exist"


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return job["steps"]


def test_the_schemathesis_contract_fuzz_still_runs(test_python: dict[str, Any]) -> None:
    # It cannot ride inside a slice: the slice runs deselect `-m schemathesis`,
    # and it needs a real server, serially. So it is its own run, and this is
    # what notices if it disappears again.
    step = _step_running(test_python, "pytest.sh contract-fuzz")
    assert step["if"] == "contains(matrix.slice.after, 'contract-fuzz')"
    script = PYTEST_SH.read_text()
    fuzz = script[script.index("cmd_contract_fuzz() {") :]
    fuzz = fuzz[: fuzz.index("\n}\n")]
    assert "USE_REAL_SERVICES=1" in fuzz, "the fuzz must run against real services"
    assert "test_schemathesis.py" in fuzz
    assert "-m schemathesis" in fuzz


def test_the_schemathesis_run_rides_a_slice_that_has_services(
    slices: list[dict[str, Any]],
) -> None:
    named = [s for s in slices if "contract-fuzz" in s["after"]]
    assert named, "no slice runs the contract fuzz"
    assert all(s["services"] == "true" for s in named), (
        "the fuzz boots a real server — it must run in a slice with services up"
    )


def test_the_slices_still_deselect_schemathesis(test_python: dict[str, Any]) -> None:
    # The control for the test above: if the slices ever stopped deselecting
    # it, the separate step would be redundant rather than load-bearing, and
    # this file would be asserting something that no longer matters.
    slice_step = [s for s in _steps(test_python) if "pytest.sh slice" in str(s.get("run", ""))]
    assert slice_step, "no step runs the slice"
    script = (REPO_ROOT / "scripts" / "ci" / "pytest.sh").read_text()
    assert "not schemathesis" in script


def test_the_quality_gate_requires_the_job_that_runs_them(workflow: dict[str, Any]) -> None:
    # Both suites now live in test-python. That is only worth anything if the
    # branch-protection target fails when test-python does.
    gate = workflow["jobs"]["quality-gate"]
    assert "test-python" in gate["needs"]


def test_local_dagger_quality_checks_run_sequentially_with_bounded_workers() -> None:
    """A local full gate must not fan out every heavy lane onto one developer Mac."""
    dagger_source = DAGGER_MODULE.read_text()
    tree = ast.parse(dagger_source)
    gaia_ci = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GaiaCi"
    )
    quality = next(
        node
        for node in gaia_ci.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "quality_checks"
    )
    source = ast.get_source_segment(DAGGER_MODULE.read_text(), quality)
    assert source is not None
    assert "asyncio.gather" not in source
    assert "worker_limit=2" in source
    assert "parallelism=1" in source
    assert source.count('"--parallel=1"') == 3
    assert '.with_env_variable("GAIA_BUILD_WORKERS", "2")' in source
    next_config = (REPO_ROOT / "apps" / "web" / "next.config.mjs").read_text()
    assert 'process.env.GAIA_BUILD_WORKERS' in next_config
