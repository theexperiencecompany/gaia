"""The mutation gate's matrix planner (scripts/ci/mutation.py plan).

The planner decides how many shards the lane fans out to and what each one
mutates. Both answers are invisible from the lane's own output: an empty
matrix is indistinguishable from a clean run, and a skipped lane counts as a
pass in the quality gate — so a regression here reads as green rather than as
broken, the exact failure mode the gate exists to prevent.

Driven as a real script against stubbed externals: the harness copies
`mutation.py` into a throwaway tree next to a fake ``changes.sh`` (which names
the changed Python files) and a fake ``lib/mutation_matrix.py`` (which prints
the module list). The script's own `matrix` subcommand — the diff filtering
between those two — runs for real. Nothing here runs mutmut.
"""

from collections.abc import Callable
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import ClassVar

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
PLAN_SCRIPT = REPO_ROOT / "scripts" / "ci" / "mutation.py"
REPORT_LIB = REPO_ROOT / "scripts" / "ci" / "lib" / "mutation_report.py"


# Read out of the script under test rather than mirrored here. A hand-copied
# constant drifts the moment the real one is retuned, and the failure lands on
# whoever changed the script rather than on this file — so parse it instead.
# The packing it drives is what keeps a huge diff producing a matrix at all,
# rather than blowing GitHub's 256-job hard limit and yielding none — and a lane
# with no matrix is a lane that counts as a pass.
def _constant(name: str) -> float:
    source = PLAN_SCRIPT.read_text()
    match = re.search(rf"^{name} = ([\d.]+)$", source, re.MULTILINE)
    assert match, f"{name} not found in mutation.py — did the plan script change shape?"
    return float(match.group(1))


MAX_SHARDS = int(_constant("MAX_SHARDS"))
MUTATION_WAVE = int(_constant("MUTATION_WAVE"))
SHARD_BUDGET_SECONDS = _constant("SHARD_BUDGET_SECONDS")
UNIT_RATE = _constant("UNIT_SECONDS_PER_MUTANT")
OVERHEAD = _constant("MODULE_OVERHEAD_SECONDS")

# Heavy enough that the whole diff needs more than MAX_SHARDS budgets, so the
# bound is what decides the count. Equal costs pack evenly, the first shards
# taking the ceiling of the split.
HUGE_DIFF_MODULES = 430
HUGE_DIFF_MUTANTS = 2000
FIRST_SHARD_SIZE = -(-HUGE_DIFF_MODULES // MAX_SHARDS)


def _install(scripts: Path) -> None:
    """Copy the script under test plus the lib it sources into the sandbox."""
    shutil.copy(PLAN_SCRIPT, scripts / "mutation.py")
    lib = scripts / "lib"
    lib.mkdir(exist_ok=True)
    shutil.copy(REPORT_LIB, lib / "mutation_report.py")


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


PlanRun = Callable[..., tuple[subprocess.CompletedProcess[str], dict[str, str]]]


@pytest.fixture
def harness(tmp_path: Path) -> PlanRun:
    """Run `mutation.py plan` against a stubbed matrix, returning its outputs."""
    scripts = tmp_path / "scripts" / "ci"
    scripts.mkdir(parents=True)
    _install(scripts)
    github_output = tmp_path / "github_output"
    github_output.touch()

    def run(
        matrix: list[dict[str, object]],
        measured: dict[str, dict[str, float]] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
        # measured: run id -> {module: seconds}, as `history` lands earlier runs' shards.
        history = tmp_path / "history"
        for run_id, durations in (measured or {}).items():
            shard = history / run_id / "mutation-durations-0"
            shard.mkdir(parents=True)
            (shard / "shard.durations.json").write_text(json.dumps(durations))
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
            [sys.executable, str(scripts / "mutation.py"), "plan"],
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": "/usr/bin:/bin",
                "GITHUB_OUTPUT": str(github_output),
                "MUTATION_HISTORY_DIR": str(history),
            },
        )
        outputs = dict(
            line.split("=", 1) for line in github_output.read_text().splitlines() if "=" in line
        )
        return process, outputs

    return run


def _entry(
    module: str, testfiles: list[str], changed_lines: list[int], mutants: int = 1
) -> dict[str, object]:
    return {
        "module": module,
        "testfiles": testfiles,
        "changed_lines": changed_lines,
        "mutants": mutants,
    }


def _matrix(outputs: dict[str, str]) -> list[dict[str, str]]:
    """Return each shard as the job sees it: its label plus the group and pool shard_defs names."""
    defs = json.loads(outputs["shard_defs"])
    return [{"label": label, **defs[label]} for label in json.loads(outputs["shards"])]


def _groups(outputs: dict[str, str]) -> list[list[dict[str, str]]]:
    """Return the modules each shard carries, unpacked from the matrix."""
    return [json.loads(item["group"]) for item in _matrix(outputs)]


def test_the_matrix_value_is_the_label_alone(harness: PlanRun) -> None:
    # Any other key would be appended to the job name, and an object value is
    # what made a skipped job render `${{ matrix.label }}` literally.
    _, outputs = harness(
        [
            _entry("app/a.py", ["tests/unit/test_a.py"], [1]),
            _entry("app/b.py", ["tests/unit/test_b.py"], [1]),
        ]
    )

    assert json.loads(outputs["shards"]) == ["app/a.py", "app/b.py"]
    assert set(json.loads(outputs["shard_defs"])) == {"app/a.py", "app/b.py"}


def test_every_changed_module_gets_its_own_shard(harness: PlanRun) -> None:
    process, outputs = harness(
        [
            _entry("app/a.py", ["tests/unit/test_a.py"], [1, 2]),
            _entry("app/b.py", ["tests/unit/test_b.py"], [7]),
        ]
    )

    assert process.returncode == 0, process.stderr
    assert outputs["count"] == "2"
    assert [group[0]["module"] for group in _groups(outputs)] == ["app/a.py", "app/b.py"]


def test_a_lone_module_names_its_own_check(harness: PlanRun) -> None:
    # The label is the check name in the PR's list; a reader picks the failing
    # module out of it without opening anything.
    _, outputs = harness([_entry("app/a.py", ["tests/unit/test_a.py"], [1])])

    assert [item["label"] for item in _matrix(outputs)] == ["app/a.py"]


def test_list_arguments_are_emitted_as_json_strings(harness: PlanRun) -> None:
    # A GitHub matrix value cannot hold nested JSON, and mutation.py parses
    # both lists back from exactly this string form.
    _, outputs = harness([_entry("app/a.py", ["tests/unit/test_a.py"], [4, 5])])

    entry = _groups(outputs)[0][0]
    assert entry["testfiles"] == '["tests/unit/test_a.py"]'
    assert entry["ranges"] == "[4,5]"


def test_a_module_with_several_test_files_keeps_all_of_them(harness: PlanRun) -> None:
    _, outputs = harness(
        [_entry("app/a.py", ["tests/unit/test_a.py", "tests/unit/test_b.py"], [1])]
    )

    entry = _groups(outputs)[0][0]
    # Compact separators, asserted on a multi-element list because a
    # single-element one renders identically either way.
    assert entry["testfiles"] == '["tests/unit/test_a.py","tests/unit/test_b.py"]'


def test_no_changed_modules_yields_an_empty_matrix_and_a_zero_count(harness: PlanRun) -> None:
    # count is what the lane's `if:` reads to skip the matrix job entirely —
    # an empty matrix with a non-zero count would start a shard with nothing
    # to mutate and report it as a pass.
    process, outputs = harness([])

    assert process.returncode == 0, process.stderr
    assert outputs["count"] == "0"
    assert _matrix(outputs) == []


class TestPackingAHugeDiff:
    """A diff too costly for MAX_SHARDS budgets still gets MAX_SHARDS shards, no more.

    GitHub refuses a matrix larger than 256 jobs outright, and the lane would
    then produce NO matrix — which the gate reads as a skip, and a skipped
    lane counts as a pass. A 430-module PR is what found this.
    """

    @staticmethod
    def _many(count: int) -> list[dict[str, object]]:
        return [
            _entry(f"app/m{i}.py", [f"tests/unit/test_m{i}.py"], [i], mutants=HUGE_DIFF_MUTANTS)
            for i in range(count)
        ]

    def test_the_matrix_never_exceeds_the_job_limit(self, harness: PlanRun) -> None:
        process, outputs = harness(self._many(HUGE_DIFF_MODULES))

        assert process.returncode == 0, process.stderr
        assert int(outputs["count"]) == MAX_SHARDS

    def test_every_module_still_runs_exactly_once(self, harness: PlanRun) -> None:
        # Packing must not drop a module: a silently unmutated module is a
        # false green, which is worse than a lane that fails.
        _, outputs = harness(self._many(HUGE_DIFF_MODULES))

        packed = [entry["module"] for group in _groups(outputs) for entry in group]
        assert sorted(packed) == sorted(f"app/m{i}.py" for i in range(HUGE_DIFF_MODULES))
        assert len(packed) == len(set(packed))

    def test_a_packed_shard_says_how_many_it_carries(self, harness: PlanRun) -> None:
        _, outputs = harness(self._many(HUGE_DIFF_MODULES))

        labels = [item["label"] for item in _matrix(outputs)]
        # Every shard says which slice it is and how much it carries, so a red
        # check is locatable without opening it.
        assert labels[0] == f"shard 1/{MAX_SHARDS} ({FIRST_SHARD_SIZE} modules)"
        assert all(
            re.fullmatch(rf"shard \d+/{MAX_SHARDS} \(\d+ modules\)", label) for label in labels
        )


def test_a_cheap_diff_of_a_wave_of_modules_gets_one_shard_each(harness: PlanRun) -> None:
    # Shards that run at once cost no wall clock, so a cheap diff still fans out.
    _, outputs = harness([_entry(f"app/m{i}.py", [UNIT_TEST], [i]) for i in range(MUTATION_WAVE)])

    assert int(outputs["count"]) == MUTATION_WAVE
    assert all(len(group) == 1 for group in _groups(outputs))


def test_a_cheap_diff_never_takes_more_than_one_wave(harness: PlanRun) -> None:
    _, outputs = harness([_entry(f"app/m{i}.py", [UNIT_TEST], [i]) for i in range(40)])

    assert int(outputs["count"]) == MUTATION_WAVE


def test_a_costly_diff_gets_as_many_shards_as_it_needs_to_fit_the_budget(
    harness: PlanRun,
) -> None:
    # PR #1799: 222 modules worth ~10,000 s were forced into six shards, and
    # every shard ran past its 28-minute deadline. The count follows the cost,
    # and shards past the wave queue behind max-parallel.
    mutants = 800  # ~260 s per module
    entries = [_entry(f"app/m{i}.py", [UNIT_TEST], [i], mutants=mutants) for i in range(40)]

    process, outputs = harness(entries)

    assert process.returncode == 0, process.stderr
    per_module = OVERHEAD + mutants * UNIT_RATE
    assert MUTATION_WAVE < int(outputs["count"]) <= MAX_SHARDS
    for group in _groups(outputs):
        assert len(group) * per_module <= SHARD_BUDGET_SECONDS
    assert "::warning::" not in process.stdout


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
        [sys.executable, str(scripts / "mutation.py"), "plan"],
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
            "scripts/ci/mutation.py",
        ],
    )
    # Echo back exactly what the filter passed in, so the assertion is about
    # the filter and not about the detector.
    _stub_detector(scripts, "import sys\nsys.stdout.write(sys.stdin.read())\n")

    process = subprocess.run(
        [sys.executable, str(scripts / "mutation.py"), "matrix"],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin"},
    )

    assert process.returncode == 0, process.stderr
    assert process.stdout.split() == ["apps/api/app/services/real.py"]


# ---------------------------------------------------------------------------
# Pools — a shard brings up the services only when its tests need them.
#
# The contract tier is in the mapped test set, and it needs live Mongo and
# Redis, which cost setup time and a test-services lane. The planner therefore
# separates the two kinds of module and labels each shard `services` or `unit`;
# the workflow conditions the services steps on that label. Mixing them would
# either start services for a shard that has no use for them or skip every
# contract test in a shard that does.
# ---------------------------------------------------------------------------

CONTRACT_TEST = "tests/contracts/test_repo.py"
UNIT_TEST = "tests/unit/test_thing.py"


def _pools(outputs: dict[str, str]) -> dict[str, list[str]]:
    """Modules by the pool their shard was assigned to."""
    by_pool: dict[str, list[str]] = {}
    for item in _matrix(outputs):
        for entry in json.loads(item["group"]):
            by_pool.setdefault(item["pool"], []).append(entry["module"])
    return by_pool


def test_a_contract_mapped_module_runs_in_the_services_pool(harness: PlanRun) -> None:
    process, outputs = harness(
        [
            _entry("app/db/repositories/users.py", [CONTRACT_TEST], [1]),
            _entry("app/services/plain.py", [UNIT_TEST], [2]),
        ]
    )

    assert process.returncode == 0, process.stderr
    assert _pools(outputs) == {
        "services": ["app/db/repositories/users.py"],
        "unit": ["app/services/plain.py"],
    }


def test_a_module_is_a_services_module_if_any_of_its_tests_is(harness: PlanRun) -> None:
    # The mapping keeps every referencing file, so the common repository module
    # carries a unit file AND a contract file. One contract file is enough: the
    # shard has to run somewhere those tests can connect.
    _, outputs = harness([_entry("app/db/repositories/users.py", [UNIT_TEST, CONTRACT_TEST], [1])])

    assert _pools(outputs) == {"services": ["app/db/repositories/users.py"]}


def test_a_unit_only_plan_stays_entirely_in_the_unit_pool(harness: PlanRun) -> None:
    # The control, and the common case: nothing is routed to the scarce
    # services pool unless it genuinely needs it.
    _, outputs = harness(
        [_entry(f"app/m{i}.py", [f"tests/unit/test_m{i}.py"], [i]) for i in range(3)]
    )

    assert set(_pools(outputs)) == {"unit"}


def test_no_shard_mixes_the_two_pools(harness: PlanRun) -> None:
    # A shard is one job on one runner. A mixed shard would be unrunnable in
    # either pool, which is the bug this split exists to prevent.
    _, outputs = harness(
        [_entry(f"app/repo{i}.py", [CONTRACT_TEST], [i]) for i in range(3)]
        + [_entry(f"app/unit{i}.py", [UNIT_TEST], [i]) for i in range(5)]
    )

    for item in _matrix(outputs):
        tests = {
            file for entry in json.loads(item["group"]) for file in json.loads(entry["testfiles"])
        }
        needs_services = any(test.startswith("tests/contracts/") for test in tests)
        assert needs_services == (item["pool"] == "services"), (
            f"shard {item['label']!r} is on the {item['pool']} pool with tests {sorted(tests)}"
        )


def test_the_two_pools_share_one_shard_budget(harness: PlanRun) -> None:
    # MAX_SHARDS bounds the PLAN, not each pool: two pools helping themselves to
    # six each would double the wave and walk back toward GitHub's job limit.
    _, outputs = harness(
        [_entry(f"app/repo{i}.py", [CONTRACT_TEST], [i]) for i in range(10)]
        + [_entry(f"app/unit{i}.py", [UNIT_TEST], [i]) for i in range(30)]
    )

    assert int(outputs["count"]) == MUTATION_WAVE
    # And both pools are represented — a budget that starved one of them would
    # leave its modules unmutated.
    assert set(_pools(outputs)) == {"unit", "services"}


def test_the_heavier_pool_gets_the_spare_shards(harness: PlanRun) -> None:
    # Every live pool starts at one shard and the rest follow the diff. The
    # typical PR touches one repository and many plain modules, so the services
    # pool takes one shard and the unit pool takes the remaining five.
    _, outputs = harness(
        [_entry("app/repo.py", [CONTRACT_TEST], [1])]
        + [_entry(f"app/unit{i}.py", [UNIT_TEST], [i]) for i in range(20)]
    )

    shards_per_pool: dict[str, int] = {}
    for item in _matrix(outputs):
        shards_per_pool[item["pool"]] = shards_per_pool.get(item["pool"], 0) + 1
    assert shards_per_pool == {"services": 1, "unit": MUTATION_WAVE - 1}


def test_a_services_shard_says_so_in_its_check_name(harness: PlanRun) -> None:
    # The check name is all a reviewer sees in the PR list; a red services
    # shard and a red unit shard are debugged in different places.
    _, outputs = harness([_entry("app/db/repositories/users.py", [CONTRACT_TEST], [1])])

    assert _matrix(outputs)[0]["label"] == "app/db/repositories/users.py (services)"


def test_the_matrix_runs_as_many_shards_at_once_as_the_plan_makes() -> None:
    """More shards than max-parallel queue behind each other; fewer leave runners idle."""
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
    assert workflow["jobs"]["test-mutation"]["strategy"]["max-parallel"] == MUTATION_WAVE
    # runner.py sizes the box's services pool for one wave of them.
    runner = (REPO_ROOT / "scripts" / "ci" / "runner.py").read_text()
    assert re.search(rf"^MUTATION_WAVE = {MUTATION_WAVE}$", runner, re.MULTILINE)


def test_a_shard_uploads_only_files_its_own_job_wrote() -> None:
    # The home runner keeps its checkout (clean: false): a shard that failed in
    # setup uploaded the previous job's shard.durations.json as its own.
    steps = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())["jobs"][
        "test-mutation"
    ]["steps"]
    shard = next(s for s in steps if s.get("run") == "python3 scripts/ci/mutation.py shard")
    uploaded = [
        line.strip()
        for s in steps
        if s.get("uses", "").startswith("actions/upload-artifact@")
        for line in s["with"]["path"].splitlines()
        if line.strip()
    ]

    assert shard["env"]["SHARD_LOG"] == "${{ runner.temp }}/shard.log"
    assert uploaded
    assert all(path.startswith("${{ runner.temp }}/shard.") for path in uploaded)


# ---------------------------------------------------------------------------
# Cost — shards are balanced by estimated work, not by module count.
#
# PR #1799 packed 222 modules six ways by count: shard 3/6 drew 54 modules and
# hit the 30-minute step timeout, while the two services shards each carried a
# ~15-minute module beside thirty others. A module's cost is its estimated
# mutant count times its mapped test files, at the pool's per-test rate.
# ---------------------------------------------------------------------------

HEAVY_MUTANTS = 2000


def _shard_of(outputs: dict[str, str], module: str) -> list[str]:
    """Return the modules sharing a shard with `module`, itself included."""
    for group in _groups(outputs):
        modules = [entry["module"] for entry in group]
        if module in modules:
            return modules
    raise AssertionError(f"{module} is in no shard")


def test_two_heavy_modules_never_share_a_shard(harness: PlanRun) -> None:
    # Round-robin by index put modules 0 and 6 together whatever they weighed.
    entries = [_entry("app/heavy0.py", [UNIT_TEST], [1], mutants=HEAVY_MUTANTS)]
    entries += [_entry(f"app/light{i}.py", [UNIT_TEST], [1]) for i in range(1, 6)]
    entries += [_entry("app/heavy6.py", [UNIT_TEST], [1], mutants=HEAVY_MUTANTS)]
    entries += [_entry(f"app/light{i}.py", [UNIT_TEST], [1]) for i in range(7, 12)]

    _, outputs = harness(entries)

    assert _shard_of(outputs, "app/heavy0.py") == ["app/heavy0.py"]
    assert _shard_of(outputs, "app/heavy6.py") == ["app/heavy6.py"]


def test_a_few_costly_services_modules_get_shards_of_their_own(harness: PlanRun) -> None:
    # Three repository modules each worth ~12 serial minutes outweigh twenty
    # cheap unit modules; by count the services pool got one shard for all three.
    contracts = [f"tests/contracts/test_repo{n}.py" for n in range(8)]
    entries = [_entry(f"app/repo{i}.py", contracts, [1], mutants=500) for i in range(3)]
    entries += [_entry(f"app/unit{i}.py", [UNIT_TEST], [i]) for i in range(20)]

    _, outputs = harness(entries)

    services = [item for item in _matrix(outputs) if item["pool"] == "services"]
    assert len(services) == 3
    assert int(outputs["count"]) == MUTATION_WAVE


def test_a_shard_over_the_budget_is_announced_by_the_plan(harness: PlanRun) -> None:
    contracts = [f"tests/contracts/test_repo{n}.py" for n in range(8)]

    process, _ = harness([_entry("app/repo.py", contracts, [1], mutants=5000)])

    assert process.returncode == 0, process.stderr
    assert "::warning::mutation plan: app/repo.py (services) is estimated at" in process.stdout


def test_each_module_carries_its_mutant_estimate_to_the_shard(harness: PlanRun) -> None:
    _, outputs = harness([_entry("app/a.py", [UNIT_TEST], [1], mutants=42)])

    assert _groups(outputs)[0][0]["mutants"] == "42"


class TestAModuleMeasuredOnAnEarlierRunIsPlannedAtThatCost:
    """No static feature predicts the slow modules (#1799: liveness.py estimated 36 s, took 673 s)."""

    SLOW: ClassVar[dict[str, float]] = {f"app/m{i}.py": 500.0 for i in range(10)}

    def _entries(self) -> list[dict[str, object]]:
        return [_entry(module, [UNIT_TEST], [1]) for module in self.SLOW]

    def test_unmeasured_modules_are_planned_from_the_estimate(self, harness: PlanRun) -> None:
        _, outputs = harness(self._entries())

        assert int(outputs["count"]) == MUTATION_WAVE

    def test_measured_modules_get_the_shards_their_real_cost_needs(self, harness: PlanRun) -> None:
        process, outputs = harness(self._entries(), {"101": self.SLOW})

        assert process.returncode == 0, process.stderr
        assert int(outputs["count"]) == len(self.SLOW)
        assert all(len(group) == 1 for group in _groups(outputs))
        assert all(group[0]["seconds"] == "500.0" for group in _groups(outputs))

    def test_one_module_alone_over_the_budget_adds_no_shards(self, harness: PlanRun) -> None:
        # More shards cannot split a single module, so a 673 s module must not
        # push 39 cheap ones from one wave out to MAX_SHARDS.
        entries = [_entry(f"app/m{i}.py", [UNIT_TEST], [1]) for i in range(40)]

        process, outputs = harness(entries, {"101": {"app/m0.py": 673.0}})

        assert process.returncode == 0, process.stderr
        assert int(outputs["count"]) == MUTATION_WAVE
        assert _shard_of(outputs, "app/m0.py") == ["app/m0.py"]

    def test_the_newest_runs_measurement_wins(self, harness: PlanRun) -> None:
        _, outputs = harness(
            [_entry("app/a.py", [UNIT_TEST], [1])],
            {"101": {"app/a.py": 900.0}, "205": {"app/a.py": 40.0}},
        )

        ((module,),) = _groups(outputs)
        assert module["seconds"] == "40.0"


GH_STUB = """#!/usr/bin/env python3
import json, os, pathlib, sys
calls = pathlib.Path(os.environ["GH_CALLS"])
calls.write_text(calls.read_text() + " ".join(sys.argv[1:]) + "\\n")
if sys.argv[1] == "api":
    print(json.dumps([9, 7, 5]))
elif sys.argv[1:3] == ["run", "download"] and sys.argv[3] == "9":
    out = pathlib.Path(sys.argv[sys.argv.index("-D") + 1]) / "mutation-durations-0"
    out.mkdir(parents=True)
    (out / "shard.durations.json").write_text(json.dumps({"app/a.py": 42.0}))
"""


def test_history_lands_the_durations_of_this_prs_earlier_runs(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(GH_STUB)
    (bin_dir / "gh").chmod(0o755)
    calls = tmp_path / "calls"
    calls.write_text("")
    history = tmp_path / "history"

    process = subprocess.run(
        [sys.executable, str(PLAN_SCRIPT), "history"],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "GH_CALLS": str(calls),
            "GITHUB_REPOSITORY": "acme/gaia",
            "PR_BRANCH": "feat/x",
            "MUTATION_HISTORY_DIR": str(history),
        },
    )

    assert process.returncode == 0, process.stderr
    downloads = [line for line in calls.read_text().splitlines() if line.startswith("run download")]
    # Each run is asked for its durations only, never its multi-MB shard logs.
    assert [line.split()[2] for line in downloads] == ["9", "7", "5"]
    assert all("-p mutation-durations-*" in line for line in downloads)
    assert "branch=feat/x&event=pull_request" in calls.read_text()
    assert "1 module(s) measured across 3 run(s)" in process.stdout
