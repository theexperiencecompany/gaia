"""Tests for scripts/ci/test-impact.py.

The map is built from a REAL coverage database (coverage's own API, dynamic
contexts and all) rather than a hand-written JSON fixture — the thing most
likely to break here is our reading of coverage's context format, and a
fixture would paper straight over that.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[5] / "scripts" / "ci" / "test-impact.py"


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
        restrict_to=kwargs.get("restrict_to", []),
        always=kwargs.get("always", []),
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


def test_a_conftest_change_widens_to_all(suite) -> None:
    ids, reason, _n, _t = run_select(suite, ["apps/api/tests/conftest.py"])
    assert ids == [ti.ALL_MARKER]
    assert "conftest" in reason


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
    ids, _reason, n, _t = run_select(suite, ["apps/web/src/App.tsx", "README.md"])
    assert ids == [] and n == 0


def test_dependency_change_under_apps_api_widens_to_all(suite) -> None:
    ids, reason, _n, _t = run_select(suite, ["apps/api/pyproject.toml"])
    assert ids == [ti.ALL_MARKER]
    assert "non-source" in reason


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
    assert out.read_text().splitlines() == [f"tests/unit/test_alpha.py::test_{i}" for i in range(4)]
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
