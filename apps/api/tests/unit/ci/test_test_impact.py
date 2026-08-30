"""Tests for scripts/ci/test_impact.py.

The map is built from a REAL coverage database (coverage's own API, dynamic
contexts and all) rather than a hand-written JSON fixture — the thing most
likely to break here is our reading of coverage's context format, and a
fixture would paper straight over that.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[5] / "scripts" / "ci" / "test_impact.py"


def load_module() -> ModuleType:
    # The filename has a hyphen (the repo's convention for CI scripts), so it
    # is not importable by name.
    spec = importlib.util.spec_from_file_location("test_impact_cli", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ti = load_module()


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


# ── record ───────────────────────────────────────────────────────────────────


@pytest.fixture
def recorded_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Run two fake 'tests' under coverage with dynamic contexts.

    ``alpha.py`` is touched by both, ``beta.py`` by only the second — the
    asymmetry is the whole point of the map.
    """
    from coverage import Coverage

    # Not named "app": the real apps/api/app package is already imported by the
    # session's conftest, and a second one under that name would never be found.
    src = tmp_path / "measured"
    src.mkdir()
    (src / "__init__.py").write_text("")
    (src / "alpha.py").write_text("def a():\n    return 1\n")
    (src / "beta.py").write_text("def b():\n    return 2\n")
    monkeypatch.chdir(tmp_path)
    # The sysmon core (CI sets COVERAGE_CORE=sysmon on PR runs for speed) does
    # not implement switch_context, so every line would land in one context.
    # The real recording lanes run with the C tracer; mirror that here.
    monkeypatch.setenv("COVERAGE_CORE", "ctrace")
    sys.path.insert(0, str(tmp_path))
    try:
        cov = Coverage(
            data_file=str(tmp_path / ".coverage.slice"),
            source=["measured"],
            config_file=False,
        )
        # relative_files mirrors apps/api/pyproject.toml, and is what makes the
        # recorded keys look like `measured/alpha.py`, not a runner path.
        cov.config.relative_files = True
        cov.start()
        try:
            cov.switch_context("tests/unit/test_alpha.py::test_one|run")
            from measured import alpha

            alpha.a()

            cov.switch_context("tests/unit/test_beta.py::test_two|setup")
            from measured import beta

            beta.b()
            cov.switch_context("tests/unit/test_beta.py::test_two|run")
            alpha.a()
        finally:
            cov.stop()
        cov.save()

        out = tmp_path / "map.json"
        assert (
            ti.main(
                [
                    "record",
                    "--coverage-db",
                    str(tmp_path / ".coverage.slice"),
                    "--out",
                    str(out),
                    "--sha",
                    "deadbeef",
                    "--slice",
                    "unit",
                ]
            )
            == 0
        )
        return json.loads(out.read_text())
    finally:
        sys.path.remove(str(tmp_path))
        for mod in ("measured.alpha", "measured.beta", "measured"):
            sys.modules.pop(mod, None)


def test_record_maps_each_source_file_to_the_tests_that_touched_it(
    recorded_map: dict,
) -> None:
    files = recorded_map["files"]
    assert files["measured/alpha.py"] == [
        "tests/unit/test_alpha.py::test_one",
        "tests/unit/test_beta.py::test_two",
    ]
    # beta was imported only by the second test — if this ever includes
    # test_one the phase/context handling has regressed into a union.
    assert files["measured/beta.py"] == ["tests/unit/test_beta.py::test_two"]


def test_record_strips_the_setup_run_teardown_suffix(recorded_map: dict) -> None:
    for tests in recorded_map["files"].values():
        assert all("|" not in t for t in tests)


def test_record_writes_meta_and_test_file_index(recorded_map: dict) -> None:
    assert recorded_map["meta"]["sha"] == "deadbeef"
    assert recorded_map["meta"]["slice"] == "unit"
    assert recorded_map["test_files"]["tests/unit/test_beta.py"] == [
        "tests/unit/test_beta.py::test_two"
    ]


def test_normalise_context_and_path() -> None:
    assert ti.normalise_context("t.py::a|teardown") == "t.py::a"
    assert ti.normalise_context("t.py::a") == "t.py::a"
    assert ti.normalise_path("/home/runner/work/gaia/apps/api/app/x.py") == "app/x.py"
    assert ti.normalise_path("./app/x.py") == "app/x.py"


# ── select ───────────────────────────────────────────────────────────────────


@pytest.fixture
def suite(tmp_path: Path):
    """A synthetic 10-test suite on disk, plus its map."""
    root = tmp_path / "api"
    (root / "app").mkdir(parents=True)
    (root / "tests" / "unit").mkdir(parents=True)
    (root / "tests" / "contracts").mkdir(parents=True)
    for name in ("alpha", "beta"):
        (root / "app" / f"{name}.py").write_text("x = 1\n")
        (root / "tests" / "unit" / f"test_{name}.py").write_text("def test_x(): pass\n")
    (root / "tests" / "contracts" / "test_api.py").write_text("def test_c(): pass\n")
    (root / "tests" / "conftest.py").write_text("")
    (root / "app" / "filler.py").write_text("x = 1\n")
    (root / "tests" / "unit" / "test_filler.py").write_text("def test_x(): pass\n")

    alpha_tests = [f"tests/unit/test_alpha.py::test_{i}" for i in range(4)]
    beta_tests = [f"tests/unit/test_beta.py::test_{i}" for i in range(4)]
    contract_tests = [f"tests/contracts/test_api.py::test_{i}" for i in range(2)]
    # Ballast so a 4-test selection sits comfortably under the 30% cutoff —
    # 30 tests total, of which 28 are in the unit slice.
    filler_tests = [f"tests/unit/test_filler.py::test_{i}" for i in range(20)]
    files = {
        "app/alpha.py": alpha_tests,
        "app/beta.py": beta_tests + contract_tests,
        "app/filler.py": filler_tests,
    }
    test_files = {
        "tests/unit/test_alpha.py": alpha_tests,
        "tests/unit/test_beta.py": beta_tests,
        "tests/unit/test_filler.py": filler_tests,
        "tests/contracts/test_api.py": contract_tests,
    }
    return root, files, test_files


def run_select(suite, changed: list[str], **kwargs):
    root, files, test_files = suite
    return ti.select_tests(
        changed,
        files,
        test_files,
        repo_root=root,
        scope=ti.SliceScope.of(
            paths=kwargs.get("restrict_to", []),
            always=kwargs.get("always", []),
            exclude=kwargs.get("exclude", []),
        ),
    )


def test_changed_source_file_selects_only_its_own_tests(suite) -> None:
    ids, _reason, n, total = run_select(suite, ["apps/api/app/alpha.py"])
    assert ids == [f"tests/unit/test_alpha.py::test_{i}" for i in range(4)]
    assert (n, total) == (4, 30)


def test_paths_are_accepted_with_or_without_the_apps_api_prefix(suite) -> None:
    with_prefix = run_select(suite, ["apps/api/app/alpha.py"])[0]
    without = run_select(suite, ["app/alpha.py"])[0]
    assert with_prefix == without != []


def test_changed_test_file_runs_that_whole_file(suite) -> None:
    ids, _r, _n, _t = run_select(suite, ["apps/api/tests/unit/test_beta.py"])
    assert ids == ["tests/unit/test_beta.py"]


def test_changed_underscore_test_module_runs_that_whole_file(suite) -> None:
    root = suite[0]
    (root / "tests" / "unit" / "beta_test.py").write_text("def test_y(): pass\n")
    ids, _r, _n, _t = run_select(suite, ["apps/api/tests/unit/beta_test.py"])
    assert ids == ["tests/unit/beta_test.py"]


@pytest.mark.parametrize(
    "rel",
    [
        "tests/unit/__snapshots__/test_render.txt",
        "tests/integration/fixtures/payload.json",
        "tests/e2e/cassettes/login.yaml",
    ],
)
def test_a_non_python_file_under_tests_widens_to_all(suite, rel: str) -> None:
    # Snapshots, fixtures and cassettes are read by tests the map cannot name,
    # and pytest collects nothing from the path itself: selecting nothing
    # here was a false green. Note .txt is inert elsewhere under apps/api.
    ids, reason, _n, _t = run_select(suite, [f"apps/api/{rel}"])
    assert ids == [ti.ALL_MARKER]
    assert "non-test file under tests/" in reason


def test_a_helper_module_under_tests_widens_to_all(suite) -> None:
    # tests/integration/real/memory/store.py-style helpers: pytest collects 0
    # tests from the positional path, and the tests importing it are unmapped.
    ids, reason, _n, _t = run_select(suite, ["apps/api/tests/integration/real/memory/store.py"])
    assert ids == [ti.ALL_MARKER]
    assert "store.py" in reason


def test_prose_under_tests_stays_inert(suite) -> None:
    ids, _reason, n, _t = run_select(suite, ["apps/api/tests/CLAUDE.md"])
    assert ids == [] and n == 0


def test_a_conftest_change_widens_to_all(suite) -> None:
    ids, reason, _n, _t = run_select(suite, ["apps/api/tests/conftest.py"])
    assert ids == [ti.ALL_MARKER]
    assert "conftest" in reason


@pytest.mark.parametrize(
    "path",
    [
        "uv.lock",
        "pyproject.toml",
        ".python-version",
        "libs/pyproject.toml",
        "scripts/ci/pytest.sh",
        "scripts/ci/test_impact.py",
        ".github/workflows/main.yml",
        ".github/actions/setup-python-test-env/action.yml",
    ],
)
def test_suite_config_outside_apps_api_widens_to_all(suite, path: str) -> None:
    # The workspace lockfile is the ROOT uv.lock (there is no apps/api/uv.lock);
    # a dependency bump used to select nothing.
    ids, reason, _n, _t = run_select(suite, [path])
    assert ids == [ti.ALL_MARKER]
    assert "test-suite config" in reason


def test_an_unmapped_app_file_widens_to_all(suite) -> None:
    root = suite[0]
    (root / "app" / "gamma.py").write_text("x = 1\n")
    ids, reason, _n, _t = run_select(suite, ["apps/api/app/gamma.py"])
    assert ids == [ti.ALL_MARKER]
    assert "not in map" in reason


def test_a_deleted_unmapped_app_file_selects_nothing(suite) -> None:
    ids, _reason, n, _t = run_select(suite, ["apps/api/app/gone.py"])
    assert ids == [] and n == 0


def test_python_outside_apps_api_widens_to_all(suite) -> None:
    ids, reason, _n, _t = run_select(suite, ["libs/shared/py/thing.py"])
    assert ids == [ti.ALL_MARKER]
    assert "outside apps/api" in reason


def test_unrelated_paths_select_nothing(suite) -> None:
    ids, _reason, n, _t = run_select(
        suite, ["apps/web/src/App.tsx", "README.md", "pnpm-lock.yaml", "libs/shared/ts/x.ts"]
    )
    assert ids == [] and n == 0


def test_dependency_change_under_apps_api_widens_to_all(suite) -> None:
    ids, reason, _n, _t = run_select(suite, ["apps/api/pyproject.toml"])
    assert ids == [ti.ALL_MARKER]
    assert "non-source" in reason


@pytest.mark.parametrize(
    "path",
    [
        "apps/api/.pre-commit-config.yaml",
        "apps/api/README.md",
        "apps/api/docs/architecture.md",
        "apps/api/.dockerignore",
        "apps/api/CLAUDE.md",
    ],
)
def test_inert_files_under_apps_api_select_nothing(suite, path: str) -> None:
    # Tooling config and prose cannot change a test's outcome; widening on
    # them made every lane run its whole slice after a lint-only master merge.
    ids, _reason, n, _t = run_select(suite, [path])
    assert ids == [] and n == 0


def test_inert_file_beside_a_real_change_does_not_mask_it(suite) -> None:
    ids, _reason, n, _t = run_select(
        suite, ["apps/api/.pre-commit-config.yaml", "apps/api/app/alpha.py"]
    )
    assert n == 4 and all("test_alpha" in i for i in ids)


def test_selection_over_the_threshold_falls_back_to_all(suite) -> None:
    # alpha (4) + beta (6) + filler (20) = 30 of 30: way past 30%, so paying
    # the argv cost to express "everything" as node ids would be silly.
    ids, reason, _n, _t = run_select(
        suite,
        ["apps/api/app/alpha.py", "apps/api/app/beta.py", "apps/api/app/filler.py"],
    )
    assert ids == [ti.ALL_MARKER]
    assert "exceeds 30%" in reason


def test_restrict_to_drops_other_slices_tests_and_shrinks_the_total(suite) -> None:
    ids, _r, _n, total = run_select(suite, ["apps/api/app/beta.py"], restrict_to=["tests/unit"])
    assert ids == [f"tests/unit/test_beta.py::test_{i}" for i in range(4)]
    assert total == 28  # the two contract tests are not this slice's problem


def test_always_paths_are_appended_and_absorb_their_node_ids(suite) -> None:
    ids, _r, _n, _t = run_select(suite, ["apps/api/app/beta.py"], always=["tests/contracts"])
    # The contract node ids that app/beta.py covers must not be listed
    # separately — the directory already runs them.
    assert ids == [
        *[f"tests/unit/test_beta.py::test_{i}" for i in range(4)],
        "tests/contracts",
    ]


def test_select_cli_writes_the_file_and_prints_a_summary(
    suite, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, files, test_files = suite
    map_path = tmp_path / "map.json"
    map_path.write_text(json.dumps({"files": files, "test_files": test_files}))
    changed = tmp_path / "changed.txt"
    changed.write_text("apps/api/app/alpha.py\n\n")
    out = tmp_path / "selected.txt"

    rc = ti.main(
        [
            "select",
            "--map",
            str(map_path),
            "--changed",
            str(changed),
            "--out",
            str(out),
            "--repo-root",
            str(root),
        ]
    )
    assert rc == 0
    # tests/contracts is the built-in always-on path (the API contract), so the
    # CLI default appends it — this is what the lane really runs.
    assert out.read_text().splitlines() == [
        *[f"tests/unit/test_alpha.py::test_{i}" for i in range(4)],
        "tests/contracts",
    ]
    assert "selected 4 of 30 tests" in capsys.readouterr().out


def test_missing_map_is_treated_as_run_everything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"files": {}, "test_files": {}}))
    changed = tmp_path / "changed.txt"
    changed.write_text("apps/api/app/alpha.py\n")
    out = tmp_path / "selected.txt"

    assert (
        ti.main(
            [
                "select",
                "--map",
                str(empty),
                "--changed",
                str(changed),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    assert out.read_text().strip() == ti.ALL_MARKER
    assert "no map available" in capsys.readouterr().out


# ── off switch (the env-driven CI entry points) ──────────────────────────────


@pytest.mark.parametrize("value", ["0", "false"])
def test_select_script_disabled_writes_all_without_selecting(tmp_path: Path, value: str) -> None:
    # No map dir, no git remote: if the script got past the switch it would
    # fail on the missing merge-base, so a clean ALL proves the early exit.
    env = {
        "PATH": os.environ["PATH"],
        "SLICE_NAME": "unit-a",
        "SLICE_PATHS": "tests/unit",
        "TEST_IMPACT_ENABLED": value,
        "GITHUB_OUTPUT": str(tmp_path / "out.txt"),
    }
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "select"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert (
        f"test impact (unit-a): disabled by TEST_IMPACT_ENABLED={value}, running ALL" in proc.stdout
    )
    assert (tmp_path / "apps/api/.test-impact/selected-unit-a.txt").read_text() == "ALL\n"
    assert "mode=all" in (tmp_path / "out.txt").read_text()


def test_fetch_script_disabled_downloads_nothing(tmp_path: Path) -> None:
    env = {"PATH": os.environ["PATH"], "SLICE_NAME": "unit-a", "TEST_IMPACT_ENABLED": "0"}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "fetch"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "disabled by TEST_IMPACT_ENABLED=0" in proc.stdout
    # GITHUB_REPOSITORY is unset: any attempt at `gh api` would have failed.
    assert not (tmp_path / ".test-impact-map").exists()
