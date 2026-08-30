"""main.yml must still run every Python suite that exists.

Two suites were dropped silently when the `test-python-coverage` job was
removed: `libs/shared/py/tests` and the schemathesis contract fuzz. Nothing
went red — the job that ran them simply stopped existing, and a suite that no
longer runs looks exactly like a suite with no failures.

That is the failure mode these tests exist to make impossible: a test file can
only stop running here by someone editing THIS file, which a reviewer sees.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
MAIN_YML = REPO_ROOT / ".github" / "workflows" / "main.yml"


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(MAIN_YML.read_text())


@pytest.fixture(scope="module")
def test_python(workflow: dict[str, Any]) -> dict[str, Any]:
    return workflow["jobs"]["test-python"]


@pytest.fixture(scope="module")
def slices(test_python: dict[str, Any]) -> list[dict[str, Any]]:
    return test_python["strategy"]["matrix"]["slice"]


def test_the_gaia_shared_suite_still_runs(test_python: dict[str, Any]) -> None:
    # gaia-shared is imported by the API; its tests had their own step in the
    # retired coverage job and went with it.
    steps = [s for s in _steps(test_python) if "libs/shared/py/tests" in str(s.get("run", ""))]
    assert steps, "nothing runs libs/shared/py/tests — the gaia-shared suite is not running"


def test_gaia_shared_runs_in_its_own_pytest_invocation(test_python: dict[str, Any]) -> None:
    # NOT as a slice path. Handing pytest paths from two trees at once moves
    # rootdir to the repo root, apps/api/pytest.ini stops being the inifile,
    # and asyncio_mode/marker registration vanish — which killed the whole
    # slice (2145 failed, 891 errors) the one time it was tried.
    for entry in test_python["strategy"]["matrix"]["slice"]:
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
    # and it needs a real server, serially. So it is its own step, and this is
    # what notices if that step disappears again.
    fuzz = [s for s in _steps(test_python) if "-m schemathesis" in str(s.get("run", ""))]
    assert fuzz, "no step runs the schemathesis contract fuzz"
    (step,) = fuzz
    assert step.get("env", {}).get("USE_REAL_SERVICES") == "1", (
        "the fuzz must run against real services, or it fuzzes mocks"
    )
    assert "test_schemathesis.py" in step["run"]


def test_the_schemathesis_step_runs_in_a_slice_that_has_services(
    test_python: dict[str, Any], slices: list[dict[str, Any]]
) -> None:
    (step,) = [s for s in _steps(test_python) if "-m schemathesis" in str(s.get("run", ""))]
    condition = str(step.get("if", ""))
    named = [s for s in slices if f"'{s['name']}'" in condition]
    assert named, f"the fuzz step's `if` names no slice: {condition!r}"
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
