"""scripts/test/mutation_classify.py — verdicts for surviving mutants.

Runs the real script as a subprocess against a synthetic mutmut workdir: the
classifier reads argv at import, so exercising it in-process would need to
re-import per case.
"""

import ast
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
CLASSIFIER = REPO_ROOT / "scripts" / "test" / "mutation_classify.py"
MODULE_PATH = "app/pkg/mod.py"

ORIGINAL = textwrap.dedent(
    """
    class Filter:
        def __init__(self) -> None:
            self.flag = False

        def held(self, tail: str) -> int:
            for length in range(len(tail), 0, -1):
                if tail[-length:] == "[":
                    return length
            return 0

        def walk(self, items: list[str]) -> list[str]:
            def visit(item: str) -> str:
                return item.strip()

            seen = [visit(item) for item in items]
            return seen[:10]
    """
).lstrip()


def _method_source(method: str) -> str:
    tree = ast.parse(ORIGINAL)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == method)
    return "\n".join(ORIGINAL.splitlines()[node.lineno - 1 : node.end_lineno])


def _mutants_copy(method: str, mutated_line: str, orig_line: str) -> str:
    """The shape mutmut 3.x writes for a class: methods renamed
    ``xǁClassǁmethod__mutmut_<n>`` and a per-method dict whose ``_mutmut_orig``
    entry is the QUALIFIED ``Class.xǁClassǁmethod__mutmut_orig``."""
    orig = f"xǁFilterǁ{method}__mutmut_orig"
    mut = f"xǁFilterǁ{method}__mutmut_1"
    source = _method_source(method)
    return "\n".join(
        [
            "class Filter:",
            source.replace(f"def {method}", f"def {orig}", 1),
            "",
            source.replace(f"def {method}", f"def {mut}", 1).replace(orig_line, mutated_line),
            "",
            f"mutants_xǁFilterǁ{method}__mutmut['_mutmut_orig'] = Filter.{orig}",
            f"mutants_xǁFilterǁ{method}__mutmut['{mut}'] = Filter.{mut}",
            "",
        ]
    )


def _run(workdir: Path, mutant: str, changed: str = "[[1,20]]") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CLASSIFIER),
            f"    app.pkg.mod.{mutant}: survived",
            str(workdir),
            changed,
            MODULE_PATH,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    (tmp_path / "app" / "pkg").mkdir(parents=True)
    (tmp_path / "app" / "pkg" / "mod.py").write_text(ORIGINAL)
    (tmp_path / "mutants" / "app" / "pkg").mkdir(parents=True)
    return tmp_path


@pytest.mark.unit
class TestMethodMutants:
    def test_a_real_change_in_a_method_body_is_a_changed_verdict(self, workdir: Path) -> None:
        (workdir / "mutants" / MODULE_PATH).write_text(
            _mutants_copy("held", "return 1", "return 0")
        )

        result = _run(workdir, "xǁFilterǁheld__mutmut_1")

        assert result.returncode == 1, result.stderr
        assert result.stdout.strip().startswith("CHANGED:")

    def test_a_dunder_method_mutant_is_classified_not_crashed(self, workdir: Path) -> None:
        (workdir / "mutants" / MODULE_PATH).write_text(
            _mutants_copy("__init__", "self.flag = True", "self.flag = False")
        )

        result = _run(workdir, "xǁFilterǁ__init____mutmut_1")

        assert result.returncode == 1, result.stderr
        assert result.stdout.strip().startswith("CHANGED:")

    def test_a_change_after_a_nested_function_is_still_seen(self, workdir: Path) -> None:
        (workdir / "mutants" / MODULE_PATH).write_text(
            _mutants_copy("walk", "return seen[:11]", "return seen[:10]")
        )

        result = _run(workdir, "xǁFilterǁwalk__mutmut_1")

        assert result.returncode == 1, result.stderr
        assert result.stdout.strip().startswith("CHANGED:")

    def test_an_identical_method_body_is_equivalent(self, workdir: Path) -> None:
        (workdir / "mutants" / MODULE_PATH).write_text(
            _mutants_copy("held", "return 0", "return 0")
        )

        result = _run(workdir, "xǁFilterǁheld__mutmut_1")

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "EQUIV"

    def test_a_body_the_classifier_cannot_find_is_a_failure_not_equivalence(
        self, workdir: Path
    ) -> None:
        source = _mutants_copy("held", "return 1", "return 0").replace(
            "def xǁFilterǁheld__mutmut_1", "def xǁFilterǁrenamed__mutmut_1"
        )
        (workdir / "mutants" / MODULE_PATH).write_text(source)

        result = _run(workdir, "xǁFilterǁheld__mutmut_1")

        assert result.returncode == 1
        assert result.stdout.strip() == ""
