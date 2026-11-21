"""mutation_classify.py reads a package __init__.py's mutants, which mutmut names without it."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

CLASSIFY = Path(__file__).resolve().parents[2] / "test" / "mutation_classify.py"

SOURCE = "def total(a, b):\n    return a + b\n"
MUTATED = (
    "from mutmut.mutation.trampoline import wrap_in_trampoline as _mutmut_mutated, MutantDict\n"
    "mutants_x_total__mutmut: MutantDict = {}  # type: ignore\n"
    "@_mutmut_mutated(mutants_x_total__mutmut)\n"
    "def total(a, b):\n"
    "    return a + b\n"
    "def x_total__mutmut_orig(a, b):\n"
    "    return a + b\n"
    "def x_total__mutmut_1(a, b):\n"
    "    return a - b\n"
    "\n"
    "mutants_x_total__mutmut['_mutmut_orig'] = x_total__mutmut_orig # type: ignore\n"
    "mutants_x_total__mutmut['x_total__mutmut_1'] = x_total__mutmut_1 # type: ignore\n"
)


def _classify(tmp_path: Path, module_path: str, survivor: str) -> subprocess.CompletedProcess[str]:
    for root in (tmp_path, tmp_path / "mutants"):
        target = root / module_path
        target.parent.mkdir(parents=True)
        target.write_text(SOURCE if root == tmp_path else MUTATED)
    return subprocess.run(
        [
            sys.executable,
            str(CLASSIFY),
            f"{survivor}: survived",
            str(tmp_path),
            "[[2,2]]",
            module_path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_survivor_of_a_package_init_is_classified_not_a_crash(tmp_path: Path) -> None:
    result = _classify(tmp_path, "app/pkg/__init__.py", "app.pkg.x_total__mutmut_1")
    assert result.returncode == 1, result.stderr
    assert result.stdout.strip() == "CHANGED:2"


def test_a_survivor_of_a_plain_module_is_classified(tmp_path: Path) -> None:
    result = _classify(tmp_path, "app/pkg/mod.py", "app.pkg.mod.x_total__mutmut_1")
    assert result.returncode == 1, result.stderr
    assert result.stdout.strip() == "CHANGED:2"
