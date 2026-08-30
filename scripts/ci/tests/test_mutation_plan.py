"""The mutation gate's matrix planner (scripts/ci/mutation.sh plan).

The planner decides how many shards the lane fans out to and what each one
mutates. Both answers are invisible from the lane's own output: an empty
matrix is indistinguishable from a clean run, and a skipped lane counts as a
pass in the quality gate — so a regression here reads as green rather than as
broken, the exact failure mode the gate exists to prevent.

Driven as a real script against stubbed externals: the harness copies
`mutation.sh` into a throwaway tree next to a fake ``changes.sh`` (which names
the changed Python files) and a fake ``lib/mutation_matrix.py`` (which prints
the module list). The script's own `matrix` subcommand — the diff filtering
between those two — runs for real. Nothing here runs mutmut.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLAN_SCRIPT = REPO_ROOT / "scripts" / "ci" / "mutation.sh"
LOG_LIB = REPO_ROOT / "scripts" / "ci" / "lib" / "log.sh"

# Mirrors MAX_SHARDS in the script under test, which tracks the matrix's
# max-parallel: a wider matrix cannot finish sooner, it only adds a check row
# and a full setup per job. The packing below is also what keeps a huge diff
# producing a matrix at all, rather than blowing GitHub's 256-job hard limit
# and yielding none — and a lane with no matrix is a lane that counts as a pass.
MAX_SHARDS = 4


def _install(scripts: Path) -> None:
    """Copy the script under test plus the lib it sources into the sandbox."""
    shutil.copy(PLAN_SCRIPT, scripts / "mutation.sh")
    lib = scripts / "lib"
    lib.mkdir(exist_ok=True)
    shutil.copy(LOG_LIB, lib / "log.sh")


def _stub_changes(scripts: Path, changed: list[str]) -> None:
    """`changes.sh files py` — the changed-file list `matrix` filters."""
    stub = scripts / "changes.sh"
    stub.write_text("#!/usr/bin/env bash\n" + "".join(f"echo {p}\n" for p in changed))
    stub.chmod(0o755)


def _stub_detector(scripts: Path, body: str) -> None:
    """`lib/mutation_matrix.py` — the AST detector `matrix` pipes modules into."""
    stub = scripts / "lib" / "mutation_matrix.py"
    stub.write_text(body)
    stub.chmod(0o755)


@pytest.fixture
def harness(tmp_path: Path):
    """Run `mutation.sh plan` against a stubbed matrix, returning its outputs."""
    scripts = tmp_path / "scripts" / "ci"
    scripts.mkdir(parents=True)
    _install(scripts)
    github_output = tmp_path / "github_output"
    github_output.touch()

    def run(
        matrix: list[dict[str, object]],
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
        # The changed-file list the real `matrix` filtering runs over: every
        # module in the fixture, under the apps/api/app/ prefix it selects on.
        _stub_changes(
            scripts,
            [f"apps/api/{entry['module']}" for entry in matrix] or ["libs/shared/py/x.py"],
        )
        _stub_detector(
            scripts,
            f"import sys\nsys.stdin.read()\nprint({json.dumps(json.dumps(matrix))})\n",
        )
        process = subprocess.run(
            ["bash", str(scripts / "mutation.sh"), "plan"],
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
        assert labels[0] == f"shard 1/{MAX_SHARDS} (108 modules)"
        assert all(
            re.fullmatch(rf"shard \d+/{MAX_SHARDS} \(\d+ modules\)", label) for label in labels
        )

    def test_exactly_the_limit_still_gets_one_module_each(self, harness) -> None:
        _, outputs = harness(self._many(MAX_SHARDS))

        assert int(outputs["count"]) == MAX_SHARDS
        assert all(len(group) == 1 for group in _groups(outputs))


def test_a_failing_detector_fails_the_plan(tmp_path: Path) -> None:
    # The detector is what fails loudly when changed app code has no test file
    # anywhere. That failure lands on this job, and the quality gate requires
    # it by name — a plan that swallowed the error would skip the matrix, and a
    # skipped lane counts as a pass.
    scripts = tmp_path / "scripts" / "ci"
    (scripts / "lib").mkdir(parents=True, exist_ok=True)
    _install(scripts)
    _stub_changes(scripts, ["apps/api/app/a.py"])
    _stub_detector(
        scripts,
        "import sys\nsys.stderr.write('no test file for app/a.py')\nraise SystemExit(1)\n",
    )

    process = subprocess.run(
        ["bash", str(scripts / "mutation.sh"), "plan"],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "GITHUB_OUTPUT": str(tmp_path / "out")},
    )

    assert process.returncode != 0


def test_matrix_only_offers_the_detector_mutatable_app_modules(tmp_path: Path) -> None:
    # `matrix` filters the diff before the detector sees it: only apps/api/app
    # sources, and never the entry points or package files that have nothing
    # meaningful to mutate. Handing those through would fail the detector's
    # "no test file" check on files that were never mutation targets.
    scripts = tmp_path / "scripts" / "ci"
    (scripts / "lib").mkdir(parents=True, exist_ok=True)
    _install(scripts)
    _stub_changes(
        scripts,
        [
            "apps/api/app/services/real.py",
            "apps/api/app/main.py",
            "apps/api/app/worker.py",
            "apps/api/app/services/__init__.py",
            "libs/shared/py/elsewhere.py",
            "scripts/ci/mutation.sh",
        ],
    )
    # Echo back exactly what the filter passed in, so the assertion is about
    # the filter and not about the detector.
    _stub_detector(scripts, "import sys\nsys.stdout.write(sys.stdin.read())\n")

    process = subprocess.run(
        ["bash", str(scripts / "mutation.sh"), "matrix"],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin"},
    )

    assert process.returncode == 0, process.stderr
    assert process.stdout.split() == ["apps/api/app/services/real.py"]
