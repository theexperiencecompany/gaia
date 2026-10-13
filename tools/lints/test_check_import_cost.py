"""Behaviour tests for tools/lints/check_import_cost.py.

The budgets are measured, not declared, so the thing under test is the
measurement: does a module that is genuinely slow to import get caught, does
a cheap one stay quiet, and does the failure name the edge that is paying.
A deliberately slow throwaway package is the only honest fixture for that —
a canned `-X importtime` blob would prove the parser and nothing else, so
both are here.
"""

from __future__ import annotations

from pathlib import Path
import sys
import textwrap

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import check_import_cost as cost  # the path insert above must precede this import

# A real tail of `python -X importtime -c "import app.constants.llm"`: children
# before parents, two spaces per level.
IMPORTTIME = """\
import time:       120 |        120 |       transformers.utils
import time:       300 |        420 |     transformers
import time:        50 |        470 |   app.agents.llm.types
import time:        10 |         10 |   enum
import time:        80 |        560 | app.constants.llm
"""


def test_the_tree_is_rebuilt_from_a_stream_that_prints_children_first() -> None:
    root = cost.parse_importtime(IMPORTTIME)
    assert root is not None
    assert root.name == "app.constants.llm"
    assert root.cumulative_us == 560
    assert [child.name for child in root.children] == ["enum", "app.agents.llm.types"]


def test_the_chain_follows_the_money_not_the_first_import() -> None:
    """`enum` is imported first and costs nothing; the reader needs the other edge."""
    root = cost.parse_importtime(IMPORTTIME)
    assert root is not None
    assert cost.hot_chain(root) == (
        "app.constants.llm -> app.agents.llm.types (0 ms) -> transformers (0 ms) "
        "-> transformers.utils (0 ms)"
    )


def test_output_with_no_importtime_lines_is_not_a_zero_cost_pass() -> None:
    assert cost.parse_importtime("Traceback (most recent call last):\n") is None


@pytest.fixture
def package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a throwaway apps/api whose constants layer has one slow module."""
    api = tmp_path / "apps" / "api"
    constants = api / "app" / "constants"
    constants.mkdir(parents=True)
    (tmp_path / "libs").mkdir()
    (api / "app" / "__init__.py").write_text("")
    (constants / "__init__.py").write_text("")
    (constants / "cheap.py").write_text("LIMIT = 10\n")
    (api / "app" / "heavy.py").write_text("import time\n\ntime.sleep(0.5)\n")
    (constants / "slow.py").write_text(
        textwrap.dedent("""
            import app.heavy

            LIMIT = app.heavy.__name__
            """)
    )
    monkeypatch.setattr(cost, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cost, "API_ROOT", api)
    return api


def test_a_module_that_is_slow_to_import_is_over_budget_and_names_what_costs(
    package: Path,
) -> None:
    measured = cost.measure("app.constants.slow", Path(sys.executable))

    assert measured.error == ""
    assert measured.cost_ms > cost.MODULE_BUDGET_MS, measured
    assert measured.chain.startswith("app.constants.slow -> app.heavy")
    assert cost.over_budget([measured]) == [measured]

    violation = cost.violation(measured)
    assert violation.path == package / "app" / "constants" / "slow.py"
    assert "app.heavy" in violation.detail
    assert f"budget {cost.MODULE_BUDGET_MS} ms" in violation.detail


@pytest.mark.usefixtures("package")
def test_a_cheap_module_is_left_alone() -> None:
    measured = cost.measure("app.constants.cheap", Path(sys.executable))

    assert measured.error == ""
    assert measured.cost_ms < cost.MODULE_BUDGET_MS, measured
    assert cost.over_budget([measured]) == []


def test_a_module_that_cannot_be_imported_fails_rather_than_measuring_zero(
    package: Path,
) -> None:
    """An unimportable module used to look exactly like a free one."""
    (package / "app" / "constants" / "broken.py").write_text("import no_such_package\n")

    measured = cost.measure("app.constants.broken", Path(sys.executable))

    assert measured.cost_ms == 0
    assert "no_such_package" in measured.error
    assert cost.over_budget([measured]) == [measured]
    assert "could not be imported" in cost.violation(measured).detail


def test_every_tracked_module_in_the_layers_is_measured_without_being_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new file is covered the moment it is committed, not when someone adds it here."""
    listed = "apps/api/app/constants/__init__.py\0apps/api/app/constants/brand_new.py\0"

    class Proc:
        stdout = listed

    monkeypatch.setattr("check_import_cost.subprocess.run", lambda *_a, **_k: Proc())
    assert cost.tracked_modules() == ["app.constants", "app.constants.brand_new"]


def test_an_entry_point_carries_its_own_budget_and_a_layer_module_the_shared_one() -> None:
    assert cost.budget_for("app.main") == cost.ENTRY_BUDGET_MS["app.main"]
    assert cost.budget_for("app.constants.llm") == cost.MODULE_BUDGET_MS


def test_only_the_cheapest_of_the_confirming_runs_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    """The box runs the test and mutation lanes on the same cores; one slow read is a coin flip."""
    reads = iter(
        [
            [cost.Measurement("app.constants.x", 310, "chain")],
            [cost.Measurement("app.constants.x", 90, "chain")],
        ]
    )
    monkeypatch.setattr(cost, "measure_all", lambda *_a: next(reads))

    confirmed = cost.confirm([cost.Measurement("app.constants.x", 400, "chain")], Path("python"))

    assert [m.cost_ms for m in confirmed] == [90]
    assert cost.over_budget(confirmed) == []


def test_a_confirming_run_that_errors_never_replaces_a_real_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subprocess killed by the box's load must not read as "cost 0, so it passes"."""
    reads = iter(
        [
            [cost.Measurement("app.constants.x", 0, "", error="killed")],
            [cost.Measurement("app.constants.x", 0, "", error="killed")],
        ]
    )
    monkeypatch.setattr(cost, "measure_all", lambda *_a: next(reads))

    confirmed = cost.confirm([cost.Measurement("app.constants.x", 900, "chain")], Path("python"))

    assert [m.cost_ms for m in confirmed] == [900]
    assert cost.over_budget(confirmed) == confirmed


def test_the_trend_records_only_the_entry_points_and_gates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    cost.write_trend(
        [
            cost.Measurement("app.main", 4200, "chain"),
            cost.Measurement("app.constants.cheap", 40, "chain"),
        ]
    )

    written = summary.read_text()
    assert "`app.main` | 4200 ms" in written
    assert "app.constants.cheap" not in written
