"""test_impact.py: the rules that decide how narrow a PR's test run may be.

Every test here names a way the selector could hand back a run that is too
narrow — the one failure mode that reads as a green PR on a broken tree:

* a change to a `scripts/ci/` script that reshapes the environment (services,
  sidecar, parallelism, image digests) left the recorded map trusted, so the
  selection was computed against a suite that no longer exists;
* `unit-b` re-ran the files `unit-a` owns, because the slice's `--ignore`
  flags were invisible to the selector — and counted them in its own `total`,
  so the 30% ALL_THRESHOLD was measured against the wrong denominator;
* the map artifact was resolved by its run's `head_branch` STRING, so a fork
  PR from a branch it named "master" could publish the map that decides which
  of our tests run against its own diff.

The selection rules that were already covered live in
apps/api/tests/unit/ci/test_test_impact.py; this file covers what the
consolidation added.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import pytest

CI = Path(__file__).resolve().parent.parent
SCRIPT = CI / "test_impact.py"


def _load() -> ModuleType:
    # Loaded by path: a hyphen-free name still is not importable from here,
    # and the script is not part of any package.
    spec = importlib.util.spec_from_file_location("test_impact_cli", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ti = _load()


# `select` and `fetch` fall back to the slice's own environment so a workflow
# step stays one command line. That makes these tests inherit whatever the job
# running them exported — and test-python DOES export SLICE_NAME/SLICE_PATHS/
# SLICE_IGNORE. Under unit-b the ambient SLICE_PATHS restricted the selection
# to tests/unit, which dropped the always-on tests/contracts and moved the
# total from 30 to 28: green locally, red in CI, for a reason that had nothing
# to do with the code under test. Clear the lot so every test states its own
# inputs.
CI_ENV = (
    "SLICE_NAME",
    "SLICE_PATHS",
    "SLICE_IGNORE",
    "BASE_REF",
    "MAP_DIR",
    "TEST_IMPACT_ENABLED",
    "GITHUB_OUTPUT",
    "GITHUB_STEP_SUMMARY",
    "GITHUB_REPOSITORY",
    "GITHUB_HEAD_REF",
)


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in CI_ENV:
        monkeypatch.delenv(name, raising=False)


# ── suite config: anything shaping the environment widens to ALL ─────────────


@pytest.mark.parametrize(
    "path",
    [
        # Not test_impact.py itself: these are the OTHER scripts in the
        # directory, each of which decides something the map cannot see.
        "scripts/ci/test-services.sh",
        "scripts/ci/embedding-sidecar.sh",
        "scripts/ci/runner.sh",
        "scripts/ci/lib/service-images.sh",
        "scripts/ci/lib/log.sh",
        "scripts/ci/pytest.sh",
        ".github/actions/setup-python-test-env/action.yml",
        ".github/workflows/main.yml",
    ],
)
def test_every_environment_shaping_file_is_suite_config(path: str) -> None:
    assert ti.is_suite_config(path), f"{path} must invalidate the map"


def test_a_ci_script_change_widens_the_selection_to_all(tmp_path: Path) -> None:
    ids, reason, _, _ = ti.select_tests(
        ["scripts/ci/test-services.sh"],
        {"app/alpha.py": ["tests/unit/test_alpha.py::test_a"]},
        {"tests/unit/test_alpha.py": ["tests/unit/test_alpha.py::test_a"]},
        repo_root=tmp_path,
        scope=ti.SliceScope.of(),
    )
    assert ids == [ti.ALL_MARKER]
    assert "test-suite config changed" in reason


def test_an_unrelated_script_outside_scripts_ci_is_not_suite_config() -> None:
    # The widening is scoped: scripts/dev and scripts/test do not shape the
    # lane's environment, and treating them as config would run everything on
    # every tooling tweak.
    assert not ti.is_suite_config("scripts/dev/verify-lanes.json")


# ── a slice honours its own exclusions ───────────────────────────────────────


@pytest.fixture
def two_slice_suite(tmp_path: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """A map shaped like unit-a's directories plus the rest of unit-b's."""
    files = {
        "app/svc.py": ["tests/unit/services/test_svc.py::test_a"],
        "app/util.py": ["tests/unit/util/test_util.py::test_a"],
    }
    test_files = {
        "tests/unit/services/test_svc.py": [
            f"tests/unit/services/test_svc.py::test_{i}" for i in range(6)
        ],
        "tests/unit/util/test_util.py": [
            f"tests/unit/util/test_util.py::test_{i}" for i in range(4)
        ],
    }
    for rel in test_files:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    return tmp_path, files, test_files


UNIT_B_PATHS = ["tests/unit"]
UNIT_B_IGNORE = ["tests/unit/services"]


def test_unit_b_does_not_rerun_a_file_unit_a_owns(two_slice_suite) -> None:
    root, files, test_files = two_slice_suite
    ids, _, _, _ = ti.select_tests(
        ["apps/api/app/svc.py"],
        files,
        test_files,
        repo_root=root,
        scope=ti.SliceScope.of(paths=UNIT_B_PATHS, exclude=UNIT_B_IGNORE),
    )
    # app/svc.py's only tests live in unit-a's directory, so unit-b runs none.
    assert ids == []


def test_a_changed_test_file_in_the_excluded_directory_is_dropped(two_slice_suite) -> None:
    root, files, test_files = two_slice_suite
    ids, _, _, _ = ti.select_tests(
        ["apps/api/tests/unit/services/test_svc.py"],
        files,
        test_files,
        repo_root=root,
        scope=ti.SliceScope.of(paths=UNIT_B_PATHS, exclude=UNIT_B_IGNORE),
    )
    assert ids == []


def test_the_total_denominator_excludes_the_other_slices_tests(two_slice_suite) -> None:
    root, files, test_files = two_slice_suite
    _, _, _, total = ti.select_tests(
        ["apps/api/app/util.py"],
        files,
        test_files,
        repo_root=root,
        scope=ti.SliceScope.of(paths=UNIT_B_PATHS, exclude=UNIT_B_IGNORE),
    )
    # 4 of unit-b's own, not the 10 both directories hold: the ALL_THRESHOLD
    # is a fraction of what THIS slice runs.
    assert total == 4


def test_without_the_exclusions_the_same_change_selects_the_other_slices_tests(
    two_slice_suite,
) -> None:
    # The control: same inputs, no exclusions — this is the behaviour the
    # --exclude plumbing exists to stop, and it must still be reachable so the
    # tests above are proving the flag rather than an unrelated filter.
    root, files, test_files = two_slice_suite
    ids, _, _, total = ti.select_tests(
        ["apps/api/app/svc.py"],
        files,
        test_files,
        repo_root=root,
        scope=ti.SliceScope.of(paths=UNIT_B_PATHS),
    )
    assert ids == ["tests/unit/services/test_svc.py::test_a"]
    assert total == 10


@pytest.mark.parametrize(
    ("slice_ignore", "expected"),
    [
        ("", []),
        ("--ignore=tests/unit/services", ["tests/unit/services"]),
        (
            "--ignore=tests/unit/services --ignore=tests/unit/agents",
            ["tests/unit/services", "tests/unit/agents"],
        ),
        # A bare path is accepted too, so the matrix may state either form.
        ("tests/unit/storage", ["tests/unit/storage"]),
    ],
)
def test_slice_ignore_is_parsed_into_paths(slice_ignore: str, expected: list[str]) -> None:
    assert ti._parse_ignore(slice_ignore) == expected


# ── the map is fetched from a trusted RUN, never a branch name ───────────────

REPO = "theexperiencecompany/gaia"


def _run(**overrides: Any) -> dict[str, Any]:
    run = {
        "id": 1,
        "created_at": "2026-08-30T00:00:00Z",
        "event": "push",
        "head_repository": {"full_name": REPO},
    }
    run.update(overrides)
    return run


def _with_runs(monkeypatch: pytest.MonkeyPatch, runs: list[dict[str, Any]]) -> list[str]:
    """Stub the API and record the endpoints asked for."""
    asked: list[str] = []

    def fake(endpoint: str) -> dict[str, Any]:
        asked.append(endpoint)
        return {"workflow_runs": runs}

    monkeypatch.setattr(ti, "_gh_json", fake)
    return asked


def test_the_run_query_asks_for_successful_pushes_to_master(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = _with_runs(monkeypatch, [_run(id=7)])
    assert ti._newest_trusted_run(REPO) == (7, "2026-08-30T00:00:00Z")
    (endpoint,) = asked
    assert "actions/workflows/main.yml/runs" in endpoint
    for required in ("branch=master", "event=push", "status=success"):
        assert required in endpoint


def test_a_pull_request_run_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # The query says event=push; this re-checks the run itself, because a
    # query parameter is a filter, not a guarantee.
    _with_runs(monkeypatch, [_run(id=7, event="pull_request")])
    assert ti._newest_trusted_run(REPO) is None


def test_a_run_from_a_fork_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # The attack this closes: a fork branch NAMED master. The head repository,
    # not the branch string, is what says whose code produced the map.
    _with_runs(monkeypatch, [_run(id=7, head_repository={"full_name": "attacker/gaia"})])
    assert ti._newest_trusted_run(REPO) is None


def test_the_newest_trusted_run_wins_over_an_untrusted_newer_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The API returns newest first; the fork's run is skipped, not taken.
    _with_runs(
        monkeypatch,
        [
            _run(id=9, head_repository={"full_name": "attacker/gaia"}),
            _run(id=8, created_at="2026-08-29T00:00:00Z"),
        ],
    )
    assert ti._newest_trusted_run(REPO) == (8, "2026-08-29T00:00:00Z")


def test_no_trusted_run_leaves_no_map(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ti, "_gh_json", lambda endpoint: {"workflow_runs": []})
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("MAP_DIR", str(tmp_path / "maps"))
    monkeypatch.chdir(tmp_path)
    args = ti.build_parser().parse_args(["fetch", "--slice", "unit-a"])
    assert ti.cmd_fetch(args) == 0
    # No map, so `select` widens to ALL — never a narrower run.
    assert list((tmp_path / "maps").iterdir()) == []


def test_a_head_repository_of_null_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Deleted forks come back with head_repository: null; `or {}` must not turn
    # that into a match.
    _with_runs(monkeypatch, [_run(id=7, head_repository=None)])
    assert ti._newest_trusted_run(REPO) is None


def test_fetch_json_shape_matches_the_real_api(tmp_path: Path) -> None:
    # Guards the field names the rejection rules read. Recorded from
    # `gh api repos/:owner/:repo/actions/workflows/main.yml/runs`.
    sample = json.loads(
        json.dumps(
            {
                "workflow_runs": [
                    {
                        "id": 33202311460,
                        "event": "push",
                        "status": "completed",
                        "conclusion": "success",
                        "head_branch": "master",
                        "created_at": "2026-08-29T18:00:00Z",
                        "head_repository": {"full_name": REPO},
                    }
                ]
            }
        )
    )
    run = sample["workflow_runs"][0]
    assert run["event"] == "push"
    assert run["head_repository"]["full_name"] == REPO
    assert isinstance(run["id"], int)
