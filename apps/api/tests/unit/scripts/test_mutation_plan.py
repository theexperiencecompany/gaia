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
import shutil
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
PLAN_SCRIPT = REPO_ROOT / "scripts" / "ci" / "mutation-plan.sh"


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


def test_every_changed_module_gets_its_own_shard(harness) -> None:
    process, outputs = harness(
        [
            _entry("app/a.py", ["tests/unit/test_a.py"], [1, 2]),
            _entry("app/b.py", ["tests/unit/test_b.py"], [7]),
        ]
    )

    assert process.returncode == 0, process.stderr
    assert outputs["count"] == "2"
    assert [item["module"] for item in json.loads(outputs["matrix"])] == [
        "app/a.py",
        "app/b.py",
    ]


def test_list_arguments_are_emitted_as_json_strings(harness) -> None:
    # A GitHub matrix value cannot hold nested JSON, and mutation.sh parses
    # both lists back from exactly this string form.
    _, outputs = harness([_entry("app/a.py", ["tests/unit/test_a.py"], [4, 5])])

    entry = json.loads(outputs["matrix"])[0]
    assert entry["testfiles"] == '["tests/unit/test_a.py"]'
    assert entry["ranges"] == "[4,5]"


def test_a_module_with_several_test_files_keeps_all_of_them(harness) -> None:
    _, outputs = harness(
        [_entry("app/a.py", ["tests/unit/test_a.py", "tests/unit/test_b.py"], [1])]
    )

    entry = json.loads(outputs["matrix"])[0]
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
