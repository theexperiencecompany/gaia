"""mutation_gap.py: the line between "nothing to mutate here" and "untested".

Lives beside the classifier tests rather than in scripts/ci/tests because it
needs mutmut and the lane's patches, which only the API venv has. Each case is
a shape from a real run: line 199 of memory_backfill_tasks.py was an interior
line of a multi-line call — executed by its test, impossible to mutate — and
the AST-based first version reported it as a gap anyway.
"""

from __future__ import annotations

from collections.abc import Iterator
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
CI_DIR = REPO_ROOT / "scripts" / "ci"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before it runs: mutation.py's dataclasses resolve their module there.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gap(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ModuleType]:
    """Import mutation_gap from a workdir configure_mutmut wrote, as the lane does.

    mutmut reads [tool.mutmut] from the cwd, and importing it already loads that config.
    """
    sys.path.insert(0, str(CI_DIR))
    mutation = _load("mutation", CI_DIR / "mutation.py")
    workdir = tmp_path_factory.mktemp("lane")
    (workdir / "pyproject.toml").write_text('[project]\nname = "probe"\n')
    request = mutation.ModuleRequest(module="sample.py", testfiles=("t.py",), ranges="[[1,1]]")
    mutation.configure_mutmut(request, workdir)
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(workdir)
        yield _load("mutation_gap", CI_DIR / "lib" / "mutation_gap.py")


SOURCE = '''\
from app.x import y                       # 1
CONSTANT = "value"                        # 2
                                          # 3
def plain(a: int) -> int:                 # 4
    """Docstring."""                      # 5
    if a > 0:                             # 6
        return a * 2                      # 7
    return a                              # 8
                                          # 9
def caller(client: object) -> object:     # 10
    return client.send(                   # 11
        url=SETTINGS_URL,                 # 12
        title="Memory ready",             # 13
    )                                     # 14
                                          # 15
@decorated                                # 16
def endpoint(n: int) -> int:              # 17
    return n + 1                          # 18
                                          # 19
class Kind(StrEnum):                      # 20
    SAY_HI = "say_hi"                     # 21
                                          # 22
class Model(BaseModel):                   # 23
    collapsed: bool = False               # 24
    steps: list[int] = Field(default=[])  # 25
                                          # 26
    def total(self) -> int:               # 27
        return len(self.steps) + 1        # 28
'''


def _lines(gap: ModuleType, ranges: list[list[int]]) -> list[int]:
    return gap.mutable_changed_lines("sample.py", SOURCE, ranges)


def test_imports_and_constants_are_not_a_gap(gap: ModuleType) -> None:
    """Mutmut credits kills only through a function trampoline, so a module-level constant can never be killed."""
    assert _lines(gap, [[1, 2]]) == []


def test_a_docstring_generates_no_mutants(gap: ModuleType) -> None:
    assert _lines(gap, [[5, 5]]) == []


def test_statement_lines_in_a_plain_function_are_reported(gap: ModuleType) -> None:
    assert _lines(gap, [[6, 7]]) == [6, 7]


def test_an_interior_line_of_a_multi_line_call_is_never_a_gap(gap: ModuleType) -> None:
    """Mutmut scopes by a node's start line: line 12 belongs to the call opening on line 11 and hosts no mutant."""
    assert _lines(gap, [[12, 12]]) == []
    assert _lines(gap, [[13, 13]]) == [13]


def test_the_line_that_opens_the_call_is_reported(gap: ModuleType) -> None:
    assert _lines(gap, [[11, 11]]) == [11]


def test_a_decorated_function_counts_because_the_lane_patches_mutmut_to_mutate_it(
    gap: ModuleType,
) -> None:
    # Bare mutmut 3.7 skips decorated defs; scripts/test/mutmut_decorated_patch.py
    # lifts that for the lane, and this classifier loads the same patch.
    assert _lines(gap, [[18, 18]]) == [18]


def test_class_fields_and_enum_members_are_not_a_gap(gap: ModuleType) -> None:
    """A class-body assignment's enclosing node is its STATEMENT, not a def, so it has no trampoline to be credited through (caught via first_steps_models.py, run 34593115851)."""
    assert _lines(gap, [[21, 21]]) == []
    assert _lines(gap, [[24, 25]]) == []


def test_a_method_body_is_still_reported(gap: ModuleType) -> None:
    assert _lines(gap, [[28, 28]]) == [28]


def test_unparsable_source_reports_nothing_rather_than_crashing(gap: ModuleType) -> None:
    assert gap.mutable_changed_lines("broken.py", "def broken(:\n", [[1, 1]]) == []


def test_the_cli_prints_one_line_number_per_line(
    gap: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = tmp_path / "m.py"
    module.write_text(SOURCE)

    # Line 8 is `return a`: a bare name, nothing for mutmut to change.
    assert gap.main(["mutation_gap.py", str(module), "[[6,8]]"]) == 0
    assert capsys.readouterr().out.split() == ["6", "7"]
