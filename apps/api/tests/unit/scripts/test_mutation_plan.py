"""The mutation gate's matrix planner (scripts/ci/mutation-plan.sh).

The planner decides how many shards the lane fans out to and what each one
mutates. Both answers are invisible from the lane's own output: an empty
matrix is indistinguishable from a clean run, and a skipped lane counts as a
pass in the quality gate — so a regression here reads as green rather than as
broken, the exact failure mode the gate exists to prevent.

Driven as a real script against a stubbed sibling: the harness copies
mutation-plan.sh into a throwaway tree next to a fake ``mutation-matrix.sh``
that prints a chosen module list. Nothing here runs mutmut.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
PLAN_SCRIPT = REPO_ROOT / "scripts" / "ci" / "mutation-plan.sh"

# Mirrors MAX_SHARDS in the script under test, which tracks the matrix's
# max-parallel: a wider matrix cannot finish sooner, it only adds a check row
# and a full setup per job. The packing below is also what keeps a huge diff
# producing a matrix at all, rather than blowing GitHub's 256-job hard limit
# and yielding none — and a lane with no matrix is a lane that counts as a pass.
MAX_SHARDS = 12


@pytest.fixture
def harness(tmp_path: Path):
    """Run mutation-plan.sh against a stubbed matrix, returning its outputs."""
    scripts = tmp_path / "scripts" / "ci"
    scripts.mkdir(parents=True)
    shutil.copy(PLAN_SCRIPT, scripts / "mutation-plan.sh")
    github_output = tmp_path / "github_output"
    github_output.touch()

    def run(
        matrix: list[dict[str, object]],
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
        stub = scripts / "mutation-matrix.sh"
        stub.write_text(f"#!/usr/bin/env bash\ncat <<'JSON'\n{json.dumps(matrix)}\nJSON\n")
        stub.chmod(0o755)
        process = subprocess.run(
            ["bash", str(scripts / "mutation-plan.sh")],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": "/usr/bin:/bin", "GITHUB_OUTPUT": str(github_output)},
        )
        outputs = dict(
            line.split("=", 1) for line in github_output.read_text().splitlines() if "=" in line
        )
        return process, outputs

    return run


def _entry(module: str, testfiles: list[str], changed_lines: list[int]) -> dict[str, object]:
    return {"module": module, "testfiles": testfiles, "changed_lines": changed_lines}


def _groups(outputs: dict[str, str]) -> list[list[dict[str, str]]]:
    """The modules each shard carries, unpacked from the matrix."""
    return [json.loads(item["group"]) for item in json.loads(outputs["matrix"])]


def test_every_changed_module_gets_its_own_shard(harness) -> None:
    process, outputs = harness(
        [
            _entry("app/a.py", ["tests/unit/test_a.py"], [1, 2]),
            _entry("app/b.py", ["tests/unit/test_b.py"], [7]),
        ]
    )

    assert process.returncode == 0, process.stderr
    assert outputs["count"] == "2"
    assert [group[0]["module"] for group in _groups(outputs)] == ["app/a.py", "app/b.py"]


def test_a_lone_module_names_its_own_check(harness) -> None:
    # The label is the check name in the PR's list; a reader picks the failing
    # module out of it without opening anything.
    _, outputs = harness([_entry("app/a.py", ["tests/unit/test_a.py"], [1])])

    assert [item["label"] for item in json.loads(outputs["matrix"])] == ["app/a.py"]


def test_list_arguments_are_emitted_as_json_strings(harness) -> None:
    # A GitHub matrix value cannot hold nested JSON, and mutation.sh parses
    # both lists back from exactly this string form.
    _, outputs = harness([_entry("app/a.py", ["tests/unit/test_a.py"], [4, 5])])

    entry = _groups(outputs)[0][0]
    assert entry["testfiles"] == '["tests/unit/test_a.py"]'
    assert entry["ranges"] == "[4,5]"


def test_a_module_with_several_test_files_keeps_all_of_them(harness) -> None:
    _, outputs = harness(
        [_entry("app/a.py", ["tests/unit/test_a.py", "tests/unit/test_b.py"], [1])]
    )

    entry = _groups(outputs)[0][0]
    # Compact separators, asserted on a multi-element list because a
    # single-element one renders identically either way.
    assert entry["testfiles"] == '["tests/unit/test_a.py","tests/unit/test_b.py"]'


def test_no_changed_modules_yields_an_empty_matrix_and_a_zero_count(harness) -> None:
    # count is what the lane's `if:` reads to skip the matrix job entirely —
    # an empty matrix with a non-zero count would start a shard with nothing
    # to mutate and report it as a pass.
    process, outputs = harness([])

    assert process.returncode == 0, process.stderr
    assert outputs["count"] == "0"
    assert json.loads(outputs["matrix"]) == []


class TestPackingAHugeDiff:
    """Over MAX_SHARDS modules, shards carry several modules each.

    GitHub refuses a matrix larger than 256 jobs outright, and the lane would
    then produce NO matrix — which the gate reads as a skip, and a skipped
    lane counts as a pass. A 430-module PR is what found this.
    """

    @staticmethod
    def _many(count: int) -> list[dict[str, object]]:
        return [_entry(f"app/m{i}.py", [f"tests/unit/test_m{i}.py"], [i]) for i in range(count)]

    def test_the_matrix_never_exceeds_the_job_limit(self, harness) -> None:
        process, outputs = harness(self._many(430))

        assert process.returncode == 0, process.stderr
        assert int(outputs["count"]) == MAX_SHARDS

    def test_every_module_still_runs_exactly_once(self, harness) -> None:
        # Packing must not drop a module: a silently unmutated module is a
        # false green, which is worse than a lane that fails.
        _, outputs = harness(self._many(430))

        packed = [entry["module"] for group in _groups(outputs) for entry in group]
        assert sorted(packed) == sorted(f"app/m{i}.py" for i in range(430))
        assert len(packed) == len(set(packed))

    def test_a_packed_shard_says_how_many_it_carries(self, harness) -> None:
        _, outputs = harness(self._many(430))

        labels = [item["label"] for item in json.loads(outputs["matrix"])]
        # Every shard says which slice it is and how much it carries, so a red
        # check is locatable without opening it.
        assert labels[0] == f"shard 1/{MAX_SHARDS} (36 modules)"
        assert all(re.fullmatch(r"shard \d+/12 \(\d+ modules\)", label) for label in labels)

    def test_exactly_the_limit_still_gets_one_module_each(self, harness) -> None:
        _, outputs = harness(self._many(MAX_SHARDS))

        assert int(outputs["count"]) == MAX_SHARDS
        assert all(len(group) == 1 for group in _groups(outputs))


def test_a_failing_matrix_script_fails_the_plan(harness, tmp_path: Path) -> None:
    # The matrix script is what fails loudly when changed app code has no test
    # file anywhere. That failure lands on this job, and the quality gate
    # requires it by name — a plan that swallowed the error would skip the
    # matrix, and a skipped lane counts as a pass.
    scripts = tmp_path / "scripts" / "ci"
    scripts.mkdir(parents=True, exist_ok=True)
    shutil.copy(PLAN_SCRIPT, scripts / "mutation-plan.sh")
    stub = scripts / "mutation-matrix.sh"
    stub.write_text("#!/usr/bin/env bash\necho 'no test file for app/a.py' >&2\nexit 1\n")
    stub.chmod(0o755)

    process = subprocess.run(
        ["bash", str(scripts / "mutation-plan.sh")],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "GITHUB_OUTPUT": str(tmp_path / "out")},
    )

    assert process.returncode != 0
