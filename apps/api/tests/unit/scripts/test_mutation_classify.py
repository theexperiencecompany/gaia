"""The mutation gate's survivor classifier (scripts/test/mutation_classify.py).

The classifier is the last thing standing between a surviving mutant and the
lane's verdict, and it can be wrong in two directions. Calling a real survivor
EQUIV hides a test gap — a false green on the gate whose whole job is catching
those. Calling an unobservable mutant CHANGED demands a test nobody can write,
on a line that cannot misbehave. Both are pinned here.

Driven as a real script, the way the lane invokes it: a throwaway mutants file
in the layout mutmut emits, and the verdict read off stdout.
"""

from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
CLASSIFIER = REPO_ROOT / "scripts" / "test" / "mutation_classify.py"

MODULE_REL = "app/sample.py"
MODULE_DOTTED = "app.sample"


def _write_mutants(workdir: Path, orig_body: str, mutant_body: str) -> None:
    """Lay out the mutants file the classifier reads, as mutmut emits it."""
    target = workdir / "mutants" / MODULE_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    # The trailing dict entry is how mutmut points a mutant back at its
    # original, and it is what the classifier resolves through — without it the
    # script exits before ever comparing the two bodies.
    target.write_text(
        f"def x_probe__mutmut_orig():\n{orig_body}\n\n"
        f"def x_probe__mutmut_1():\n{mutant_body}\n\n"
        "mutants_x_probe__mutmut['_mutmut_orig'] = x_probe__mutmut_orig\n"
    )


def _classify(workdir: Path, ranges: str = "[[1,200]]") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            # The lane runs the classifier under the project venv; a bare
            # "python3" can be an older interpreter than its syntax needs.
            sys.executable,
            str(CLASSIFIER),
            f"{MODULE_DOTTED}.x_probe__mutmut_1: survived",
            str(workdir),
            ranges,
            MODULE_REL,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    # The classifier also reads the REAL module to locate the changed line, so
    # the workdir doubles as the repo root for this probe.
    (tmp_path / MODULE_REL).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / MODULE_REL).write_text("def probe():\n    return None\n")
    return tmp_path


class TestCastTypeArgument:
    """``typing.cast(T, x)`` returns x unchanged, so mutating T cannot matter.

    The single-line form was already handled. The wrapped form — which the
    formatter produces whenever the call is long — was not, because the
    normalisation runs per line and the type sits on the line after ``cast(``.
    """

    def test_a_wrapped_cast_type_argument_is_equivalent(self, workdir: Path) -> None:
        _write_mutants(
            workdir,
            "    return cast(\n        RealType,\n        value,\n    )",
            "    return cast(\n        XXMutatedTypeXX,\n        value,\n    )",
        )

        result = _classify(workdir)

        assert result.stdout.strip() == "EQUIV", result.stdout + result.stderr
        assert result.returncode == 0

    def test_a_single_line_cast_type_argument_is_equivalent(self, workdir: Path) -> None:
        _write_mutants(
            workdir,
            "    return cast(RealType, value)",
            "    return cast(XXMutatedTypeXX, value)",
        )

        result = _classify(workdir)

        assert result.stdout.strip() == "EQUIV", result.stdout + result.stderr

    def test_a_wrapped_cast_keeping_the_value_on_the_type_line_is_equivalent(
        self, workdir: Path
    ) -> None:
        # The formatter wraps after `cast(` but often leaves the VALUE beside
        # the type. Anchoring the blanking at end-of-line missed exactly this
        # shape, and reported an unkillable mutant on it.
        _write_mutants(
            workdir,
            "    return cast(\n        RealType, make(a, b),\n    )",
            "    return cast(\n        XXMutatedTypeXX, make(a, b),\n    )",
        )

        result = _classify(workdir)

        assert result.stdout.strip() == "EQUIV", result.stdout + result.stderr

    def test_a_value_change_beside_the_type_is_still_reported(self, workdir: Path) -> None:
        _write_mutants(
            workdir,
            "    return cast(\n        RealType, make(a, b),\n    )",
            "    return cast(\n        RealType, make(a, c),\n    )",
        )

        result = _classify(workdir)

        assert result.stdout.strip() != "EQUIV", result.stdout + result.stderr

    def test_a_type_argument_with_commas_is_equivalent(self, workdir: Path) -> None:
        # `dict[str, object] | None` holds a comma; a first-comma matcher
        # half-blanks it and reports a runtime no-op as a real survivor
        # (26% of one PR's failing set).
        _write_mutants(
            workdir,
            '    return cast("dict[str, object] | None", value)',
            "    return cast(None, value)",
        )

        result = _classify(workdir)

        assert result.stdout.strip() == "EQUIV", result.stdout + result.stderr
        assert result.returncode == 0

    def test_a_subscripted_type_argument_with_commas_is_equivalent(self, workdir: Path) -> None:
        _write_mutants(
            workdir,
            "    return cast(list[dict[str, object]], value)",
            "    return cast(list[None], value)",
        )

        result = _classify(workdir)

        assert result.stdout.strip() == "EQUIV", result.stdout + result.stderr

    def test_a_comma_typed_cast_with_a_changed_value_is_still_reported(self, workdir: Path) -> None:
        # Balancing must stop at the argument boundary: a VALUE change after a
        # comma-holding type is a real change.
        _write_mutants(
            workdir,
            "    return cast(tuple[str, object], value + 1)",
            "    return cast(tuple[str, object], value - 1)",
        )

        result = _classify(workdir)

        assert result.stdout.strip() != "EQUIV", result.stdout + result.stderr
        assert result.returncode == 1

    def test_a_real_change_below_a_wrapped_cast_is_still_reported(self, workdir: Path) -> None:
        # The blanking must reach the type argument and stop. A mutation to the
        # VALUE changes what the function returns.
        _write_mutants(
            workdir,
            "    return cast(\n        RealType,\n        value + 1,\n    )",
            "    return cast(\n        RealType,\n        value - 1,\n    )",
        )

        result = _classify(workdir)

        assert result.stdout.strip() != "EQUIV", result.stdout + result.stderr
        assert result.returncode == 1

    def test_a_wrapped_call_that_is_not_a_cast_is_untouched(self, workdir: Path) -> None:
        # Only ``cast(`` earns the blanking; any other wrapped call's first
        # argument is a real value.
        _write_mutants(
            workdir,
            "    return helper(\n        first_arg,\n        value,\n    )",
            "    return helper(\n        other_arg,\n        value,\n    )",
        )

        result = _classify(workdir)

        assert result.stdout.strip() != "EQUIV", result.stdout + result.stderr


class TestLookupDefaultEquivalence:
    # The default machinery re-reads the REAL module for its consumer
    # analysis, so the probe body must exist there too, at the same lines.
    _BODY = '    x = d.pop("k", {})\n    if not x:\n        return None\n    return 1'

    def _write_real_module(self, workdir: Path) -> None:
        (workdir / MODULE_REL).write_text(f"def probe(d):\n{self._BODY}\n")

    def test_a_pop_default_only_seen_by_a_truthiness_test_is_equivalent(
        self, workdir: Path
    ) -> None:
        # pop(k, d) hands back d only on a miss, same as get — and {} vs None
        # are one branch under `if not x`. This kept a whole module red.
        self._write_real_module(workdir)
        _write_mutants(
            workdir,
            self._BODY,
            '    x = d.pop("k", None)\n    if not x:\n        return None\n    return 1',
        )

        result = _classify(workdir)

        assert result.stdout.strip() == "EQUIV", result.stdout + result.stderr

    def test_a_pop_key_change_is_still_reported(self, workdir: Path) -> None:
        self._write_real_module(workdir)
        _write_mutants(
            workdir,
            self._BODY,
            '    x = d.pop("XXkXX", {})\n    if not x:\n        return None\n    return 1',
        )

        result = _classify(workdir)

        assert result.stdout.strip() != "EQUIV", result.stdout + result.stderr


class TestPopThroughCastWithEarlyExit:
    """The real stream_utils shape: pop's default flows through a cast, the
    truthiness test is `if not x: return`, and REAL reads follow the guard."""

    _BODY = (
        '    x = cast(T, d.pop("k", {}))\n'
        "    if not x:\n"
        "        return None\n"
        "    return list(x.items())"
    )

    def _write_real_module(self, workdir: Path) -> None:
        (workdir / MODULE_REL).write_text(f"def probe(d):\n{self._BODY}\n")

    def test_the_default_is_equivalent_despite_cast_and_later_reads(self, workdir: Path) -> None:
        self._write_real_module(workdir)
        _write_mutants(
            workdir,
            self._BODY,
            self._BODY.replace('d.pop("k", {})', 'd.pop("k", None)'),
        )

        result = _classify(workdir)

        assert result.stdout.strip() == "EQUIV", result.stdout + result.stderr

    def test_a_read_before_the_guard_is_still_reported(self, workdir: Path) -> None:
        body = (
            '    x = cast(T, d.pop("k", {}))\n'
            "    n = len(x)\n"
            "    if not x:\n"
            "        return None\n"
            "    return n"
        )
        (workdir / MODULE_REL).write_text(f"def probe(d):\n{body}\n")
        _write_mutants(workdir, body, body.replace('d.pop("k", {})', 'd.pop("k", None)'))

        result = _classify(workdir)

        assert result.stdout.strip() != "EQUIV", result.stdout + result.stderr


class TestContainerFunctionWithNestedDefs:
    """A mutated CONTAINER function (tool registrars) holds nested defs; the
    block split must not truncate its body at the first one — the header alone
    compares equal to every mutant, and 788 real survivors on one module were
    once stamped provably equivalent that way."""

    _ORIG = '    x = d.get("k")\n    def inner():\n        return 1\n    return (x, inner())'

    def test_a_change_beyond_the_nested_def_is_reported(self, workdir: Path) -> None:
        _write_mutants(
            workdir,
            self._ORIG,
            self._ORIG.replace('d.get("k")', 'd.get("XXkXX")'),
        )

        result = _classify(workdir)

        assert result.stdout.strip() != "EQUIV", result.stdout + result.stderr
        assert result.returncode == 1
