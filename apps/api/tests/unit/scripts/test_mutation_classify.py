"""Unit tests for the survivor classifier (scripts/test/mutation_classify.py).

The classifier decides whether a surviving mutant is a real test weakness, out
of the PR's diff, unassertable logging, or provably equivalent. It had no tests
at all, and two bugs hid in the gap between module-level functions (which it
handled) and class methods (which it did not):

* mutmut assigns a method's original as ``Class.xǁClassǁmethod__mutmut_orig``.
  A ``\\w+`` capture stopped at the dot and yielded the class name, which
  resolves to no function — the classifier exited with an empty verdict and the
  lane reported CLASSIFIER FAILED for every class-method survivor.
* the body splitter anchored ``def`` at column 0, so an indented method body was
  never found. Original and mutant both came back empty, compared equal, and
  every class-method survivor was silently reported EQUIV — a survivor
  vanishing from every bucket, which is the failure this gate exists to stop.

These fixtures mirror mutmut 3.7's real output shape for both kinds.
"""

from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[5]
CLASSIFIER = REPO_ROOT / "scripts" / "test" / "mutation_classify.py"

METHOD_MUTANTS = """\
class Widget:
    async def xǁWidgetǁstart__mutmut_orig(self) -> None:
        value = 1
        return value

    async def xǁWidgetǁstart__mutmut_1(self) -> None:
        value = 2
        return value

mutants_xǁWidgetǁstart__mutmut = {}
mutants_xǁWidgetǁstart__mutmut['_mutmut_orig'] = Widget.xǁWidgetǁstart__mutmut_orig
mutants_xǁWidgetǁstart__mutmut['xǁWidgetǁstart__mutmut_1'] = Widget.xǁWidgetǁstart__mutmut_1
"""

METHOD_SOURCE = """\
class Widget:
    async def start(self) -> None:
        value = 1
        return value
"""

FUNCTION_MUTANTS = """\
def x_compute__mutmut_orig():
    value = 1
    return value

def x_compute__mutmut_1():
    value = 2
    return value

mutants_x_compute__mutmut = {}
mutants_x_compute__mutmut['_mutmut_orig'] = x_compute__mutmut_orig
mutants_x_compute__mutmut['x_compute__mutmut_1'] = x_compute__mutmut_1
"""

FUNCTION_SOURCE = """\
def compute():
    value = 1
    return value
"""


def _workdir(tmp_path: Path, mutants: str, source: str) -> Path:
    """A workdir shaped like mutation.sh's: mutants/ copy beside the real tree."""
    (tmp_path / "mutants" / "app").mkdir(parents=True)
    (tmp_path / "mutants" / "app" / "thing.py").write_text(mutants)
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "thing.py").write_text(source)
    return tmp_path


def _classify(workdir: Path, mutant: str, ranges: str) -> tuple[str, int]:
    result = subprocess.run(
        [
            sys.executable,
            str(CLASSIFIER),
            f"    app.thing.{mutant}: survived",
            str(workdir),
            ranges,
            "app/thing.py",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip(), result.returncode


class TestClassMethodSurvivor:
    """A method's mutant must reach a real verdict, not crash and not false-EQUIV."""

    def test_survivor_on_a_changed_line_is_reported_as_changed(self, tmp_path: Path) -> None:
        workdir = _workdir(tmp_path, METHOD_MUTANTS, METHOD_SOURCE)

        verdict, code = _classify(workdir, "xǁWidgetǁstart__mutmut_1", "[[3,3]]")

        assert verdict == "CHANGED:3"
        assert code == 1

    def test_survivor_outside_the_diff_is_reported_as_unchanged(self, tmp_path: Path) -> None:
        """Out of scope is still a verdict — it must not read as equivalent."""
        workdir = _workdir(tmp_path, METHOD_MUTANTS, METHOD_SOURCE)

        verdict, code = _classify(workdir, "xǁWidgetǁstart__mutmut_1", "[[99,99]]")

        assert verdict == "UNCHANGED:3"
        assert code == 1

    def test_a_differing_method_body_is_never_called_equivalent(self, tmp_path: Path) -> None:
        """The regression: empty-vs-empty bodies compared equal and printed EQUIV."""
        workdir = _workdir(tmp_path, METHOD_MUTANTS, METHOD_SOURCE)

        verdict, _ = _classify(workdir, "xǁWidgetǁstart__mutmut_1", "[[3,3]]")

        assert verdict != "EQUIV"

    def test_the_classifier_always_emits_a_verdict(self, tmp_path: Path) -> None:
        """An empty verdict is what the lane reports as CLASSIFIER FAILED."""
        workdir = _workdir(tmp_path, METHOD_MUTANTS, METHOD_SOURCE)

        verdict, _ = _classify(workdir, "xǁWidgetǁstart__mutmut_1", "[[3,3]]")

        assert verdict != ""


class TestModuleFunctionSurvivor:
    """The path that already worked must keep working."""

    def test_survivor_on_a_changed_line_is_reported_as_changed(self, tmp_path: Path) -> None:
        workdir = _workdir(tmp_path, FUNCTION_MUTANTS, FUNCTION_SOURCE)

        verdict, code = _classify(workdir, "x_compute__mutmut_1", "[[2,2]]")

        assert verdict == "CHANGED:2"
        assert code == 1

    def test_survivor_outside_the_diff_is_reported_as_unchanged(self, tmp_path: Path) -> None:
        workdir = _workdir(tmp_path, FUNCTION_MUTANTS, FUNCTION_SOURCE)

        verdict, code = _classify(workdir, "x_compute__mutmut_1", "[[99,99]]")

        assert verdict == "UNCHANGED:2"
        assert code == 1


class TestEquivalentMutant:
    """A genuinely identical body is the one case that may report EQUIV."""

    def test_identical_bodies_are_equivalent(self, tmp_path: Path) -> None:
        mutants = METHOD_MUTANTS.replace("value = 2", "value = 1")
        workdir = _workdir(tmp_path, mutants, METHOD_SOURCE)

        verdict, code = _classify(workdir, "xǁWidgetǁstart__mutmut_1", "[[3,3]]")

        assert verdict == "EQUIV"
        assert code == 0
