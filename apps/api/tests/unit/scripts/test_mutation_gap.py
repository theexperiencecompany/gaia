"""mutation_gap.py: the line between "nothing to mutate here" and "untested".

Lives beside the classifier tests rather than in scripts/ci/tests because it
needs mutmut and the lane's patches, which only the API venv has. Each case is
a shape from a real run: line 199 of memory_backfill_tasks.py was an interior
line of a multi-line call — executed by its test, impossible to mutate — and
the AST-based first version reported it as a gap anyway.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
_SPEC = importlib.util.spec_from_file_location(
    "mutation_gap", REPO_ROOT / "scripts" / "ci" / "lib" / "mutation_gap.py"
)
assert _SPEC is not None and _SPEC.loader is not None
gap = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gap)

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


def _lines(ranges: list[list[int]]) -> list[int]:
    return gap.mutable_changed_lines("sample.py", SOURCE, ranges)


def test_imports_and_constants_are_not_a_gap() -> None:
    """mutmut does mutate a module-level constant, but it credits kills through
    a trampoline that only functions have — so nothing can ever kill it."""
    assert _lines([[1, 2]]) == []


def test_a_docstring_generates_no_mutants() -> None:
    assert _lines([[5, 5]]) == []


def test_statement_lines_in_a_plain_function_are_reported() -> None:
    assert _lines([[6, 7]]) == [6, 7]


def test_an_interior_line_of_a_multi_line_call_is_never_a_gap() -> None:
    """mutmut scopes by a node's start line: `url=SETTINGS_URL` on line 12
    belongs to the call that opens on line 11, so a PR that changed only that
    line gets no mutant there — and no test can be asked to kill one. A string
    literal is different: it is its own node, so line 13 does host mutants."""
    assert _lines([[12, 12]]) == []
    assert _lines([[13, 13]]) == [13]


def test_the_line_that_opens_the_call_is_reported() -> None:
    assert _lines([[11, 11]]) == [11]


def test_a_decorated_function_counts_because_the_lane_patches_mutmut_to_mutate_it() -> None:
    # Bare mutmut 3.7 skips decorated defs; scripts/test/mutmut_decorated_patch.py
    # lifts that for the lane, and this classifier loads the same patch.
    assert _lines([[18, 18]]) == [18]


def test_class_fields_and_enum_members_are_not_a_gap() -> None:
    """mutmut mutates a class-body assignment and tags it with the STATEMENT as
    its enclosing node, so a truthiness check reads it as function-contained.
    Only a def gets a trampoline; a field default or an enum member has no
    function to be credited through. Every changed model file read as a gap
    until this was checked by type (first_steps_models.py, run 34593115851)."""
    assert _lines([[21, 21]]) == []
    assert _lines([[24, 25]]) == []


def test_a_method_body_is_still_reported() -> None:
    assert _lines([[28, 28]]) == [28]


def test_unparsable_source_reports_nothing_rather_than_crashing() -> None:
    assert gap.mutable_changed_lines("broken.py", "def broken(:\n", [[1, 1]]) == []


def test_the_cli_prints_one_line_number_per_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = tmp_path / "m.py"
    module.write_text(SOURCE)

    # Line 8 is `return a`: a bare name, nothing for mutmut to change.
    assert gap.main(["mutation_gap.py", str(module), "[[6,8]]"]) == 0
    assert capsys.readouterr().out.split() == ["6", "7"]
