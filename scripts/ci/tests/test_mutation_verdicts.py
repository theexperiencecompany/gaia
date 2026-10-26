"""The mutation lane's verdict per mutmut outcome, end to end through `mutation.py shard`.

Every way a module's mutmut run can end is pinned here as the verdict the gate
reads (`mutation/<module>`'s status) and the shard's exit code. That is the
lane's contract with the quality gate, so it is what any rewrite of the lane
must reproduce: the same table, driven against the real script.

The sandbox's venv python is a fake that plays one scripted mutmut run per
module (its output, exit code and mutants/ tree, then what `mutmut results`,
`mutmut show`, the survivor classifier, the gap detector and a plain pytest
re-run answer) and hands every other call to the real interpreter, so the
shard, the report, `verdict.py emit` and the record merge all run as
themselves. Real mutmut against apps/api is far too heavy for a test run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from doc_shape import mapping
import pytest

CI = Path(__file__).resolve().parent.parent
MUTATION = CI / "mutation.py"
MODULE = "app/services/x.py"
SLUG = "app_services_x"
KILLED = "app.services.x.x_total__mutmut_1"
OTHER = "app.services.x.x_total__mutmut_2"

FAKE_VENV_PYTHON = f"""#!{sys.executable}
import os
from pathlib import Path
import shutil
import sys

SCENARIOS = Path(os.environ["MUTATION_SCENARIOS"])
REAL = {sys.executable!r}
args = sys.argv[1:]


def slug(module):
    return module.removesuffix(".py").replace("/", "_")


def scenario(start):
    for directory in (start, *start.parents):
        marker = directory / ".scenario-module"
        if marker.exists():
            return SCENARIOS / marker.read_text().strip()
    raise SystemExit(f"fake venv python: no scenario marker above {{start}}")


def answer(directory, name, default=""):
    path = directory / name
    return path.read_text() if path.exists() else default


if args[:1] == ["-c"]:
    module = os.environ["MUTMUT_SCOPED_MODULE"]
    Path(".scenario-module").write_text(slug(module))
    plan = SCENARIOS / slug(module)
    sys.stdout.write(answer(plan, "mutmut.out"))
    if (plan / "mutants").is_dir():
        shutil.copytree(plan / "mutants", "mutants", dirs_exist_ok=True)
    # The markers come from the plugin mutation.py loads; no directory, no plugin.
    if (plan / "in-test").is_dir() and "MUTMUT_IN_TEST_DIR" in os.environ:
        shutil.copytree(plan / "in-test", os.environ["MUTMUT_IN_TEST_DIR"], dirs_exist_ok=True)
    sys.exit(int(answer(plan, "mutmut.rc", "0")))
if args[:3] == ["-m", "mutmut", "results"]:
    plan = scenario(Path.cwd())
    sys.stdout.write(answer(plan, "results"))
    sys.exit(int(answer(plan, "results.rc", "0")))
if args[:3] == ["-m", "mutmut", "show"]:
    print(f"# {{args[3]}}: survived")
    print("--- app/services/x.py")
    print("+++ app/services/x.py")
    print("@@ -1,2 +1,2 @@")
    print(" def total(a, b):")
    print("-    return a + b")
    print("+    return a - b")
    sys.exit(0)
if args[:2] == ["-m", "pytest"]:
    sys.exit(int(answer(scenario(Path.cwd()), "plain.rc", "0")))
if args and args[0].endswith("mutation_classify.py"):
    plan = scenario(Path(args[2]))
    name = args[1].strip().rsplit(": ", 1)[0]
    verdicts = dict(row.split("\\t") for row in answer(plan, "classify").splitlines())
    verdict = verdicts.get(name, "")
    print(verdict)
    sys.exit(0 if verdict == "EQUIV" else 1)
if args and args[0].endswith("mutation_gap.py"):
    module = args[1].split("apps/api/", 1)[1]
    # The real helper asks mutmut where the code is, and mutmut reads
    # [tool.mutmut] from the cwd: run it anywhere without that section and it
    # dies before it can say whether the changed lines were reachable.
    if not (Path.cwd() / "pyproject.toml").exists():
        print("mutation_gap: cwd has no [tool.mutmut] pyproject.toml", file=sys.stderr)
        sys.exit(1)
    print(answer(SCENARIOS / slug(module), "gap"), end="")
    sys.exit(0)
os.execv(REAL, [REAL, *args])
"""


@dataclass
class Run:
    """One scripted mutmut run and everything asked about it afterwards."""

    output: str = ""
    rc: int = 0
    mutants: dict[str, str] = field(default_factory=dict)
    results: dict[str, str] = field(default_factory=dict)
    results_rc: int = 0
    classify: dict[str, str] = field(default_factory=dict)
    gap: str = ""
    plain_rc: int = 0
    raw_results: str | None = None
    killed_in_test: dict[str, str] = field(default_factory=dict)


@dataclass
class Outcome:
    returncode: int
    status: str
    verdict: dict[str, object]
    output: str


def _results(statuses: dict[str, str]) -> str:
    return "".join(f"    {name}: {status}\n" for name, status in statuses.items())


def _meta(exit_codes: dict[str, int]) -> str:
    return json.dumps(
        {
            "exit_code_by_key": exit_codes,
            "hash_by_function_name": {},
            "type_check_error_by_key": {},
            "durations_by_key": {},
            "estimated_durations_by_key": {},
        }
    )


def _write_scenario(root: Path, module: str, run: Run) -> None:
    plan = root / module.removesuffix(".py").replace("/", "_")
    plan.mkdir(parents=True)
    (plan / "mutmut.out").write_text(run.output)
    (plan / "mutmut.rc").write_text(str(run.rc))
    for relative, body in run.mutants.items():
        path = plan / "mutants" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    results = run.raw_results if run.raw_results is not None else _results(run.results)
    (plan / "results").write_text(results)
    (plan / "results.rc").write_text(str(run.results_rc))
    (plan / "classify").write_text("".join(f"{k}\t{v}\n" for k, v in run.classify.items()))
    (plan / "gap").write_text(run.gap)
    (plan / "plain.rc").write_text(str(run.plain_rc))
    (plan / "in-test").mkdir()
    for mutant, test in run.killed_in_test.items():
        (plan / "in-test" / mutant).write_text(test)


def _sandbox(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    api = root / "apps" / "api"
    (api / "app" / "services").mkdir(parents=True)
    (api / "tests" / "unit").mkdir(parents=True)
    (api / "scripts").mkdir()
    for name in ("x", "y"):
        (api / "app" / "services" / f"{name}.py").write_text("def total(a, b):\n    return a + b\n")
        (api / "tests" / "unit" / f"test_{name}.py").write_text("def test_t():\n    assert True\n")
    (api / "pyproject.toml").write_text('[tool.mutmut]\nsource_paths = ["app"]\n')
    (api / "pytest.ini").write_text("[pytest]\n")
    scripts = root / "scripts" / "ci"
    (scripts / "lib").mkdir(parents=True)
    for name in (
        MUTATION.name,
        "verdict.py",
        "lib/github.py",
        "lib/output_findings.py",
        "lib/log.sh",
        "lib/cpu-slots.sh",
        "lib/runner-host.sh",
        "lib/mutation_gap.py",
        "lib/mutation_report.py",
    ):
        shutil.copy(CI / name, scripts / name)
    venv_python = root / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text(FAKE_VENV_PYTHON)
    venv_python.chmod(0o755)
    return root


def _command(root: Path, verb: str) -> list[str]:
    return [sys.executable, str(root / "scripts" / "ci" / MUTATION.name), verb]


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k != "USE_REAL_SERVICES"}
    env.update(
        MUTATION_SCENARIOS=str(tmp_path / "scenarios"),
        MUTMUT_WORKDIR_BASE=str(work),
        RUNNER_TEMP=str(tmp_path / "runner-temp"),
        **extra,
    )
    return env


def _group(*modules: str) -> str:
    return json.dumps(
        [
            {
                "module": module,
                "testfiles": json.dumps([f"tests/unit/test_{Path(module).stem}.py"]),
                "ranges": "[[2,2]]",
            }
            for module in modules
        ]
    )


def _verdict(tmp_path: Path, module: str) -> dict[str, object]:
    path = Path(os.environ["GAIA_VERDICT_DIR"]) / "mutation" / f"{module}.json"
    return mapping(json.loads(path.read_text()))


def _shard(tmp_path: Path, run: Run) -> Outcome:
    root = _sandbox(tmp_path)
    _write_scenario(tmp_path / "scenarios", MODULE, run)
    result = subprocess.run(
        _command(root, "shard"),
        cwd=root,
        env=_env(tmp_path, GROUP=_group(MODULE), SHARD_LOG=str(root / "shard.log")),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    output = result.stdout + result.stderr
    verdict = _verdict(tmp_path, MODULE)
    return Outcome(result.returncode, str(verdict["status"]), verdict, output)


STATS = {"mutmut-stats.json": "{}"}
SURVIVOR = {KILLED: "killed", OTHER: "survived"}

# (id, the run, the gate's status, the shard's exit code)
OUTCOMES = [
    ("all-killed", Run(results={KILLED: "killed", OTHER: "killed"}), "pass", 0),
    ("survivor-on-a-changed-line", Run(results=SURVIVOR, classify={OTHER: "CHANGED:2"}), "fail", 1),
    ("survivor-off-the-diff", Run(results=SURVIVOR, classify={OTHER: "UNCHANGED:2"}), "pass", 0),
    ("survivor-equivalent", Run(results=SURVIVOR, classify={OTHER: "EQUIV"}), "pass", 0),
    ("survivor-logging-only", Run(results=SURVIVOR, classify={OTHER: "LOGGING:2"}), "pass", 0),
    ("survivor-unclassifiable", Run(results=SURVIVOR, classify={OTHER: "???"}), "error", 1),
    (
        "no-tests-on-a-changed-line",
        Run(
            results={KILLED: "killed", OTHER: "no tests"},
            classify={OTHER: "CHANGED:2"},
        ),
        "pass",
        0,
    ),
    ("no-mutants-generated", Run(output="Generating mutants\n", mutants=STATS), "skip", 0),
    ("child-never-ran", Run(), "error", 1),
    ("no-state", Run(output="something else exploded\n", rc=1, mutants={"x": ""}), "error", 1),
    (
        "no-covering-test-but-nothing-executable",
        Run(output="could not find any test case for any mutant\n", rc=1),
        "skip",
        0,
    ),
    (
        "no-covering-test-for-executable-lines",
        Run(output="could not find any test case for any mutant\n", rc=1, gap="2\n"),
        "fail",
        1,
    ),
    (
        "clean-run-artifact-of-mutmut",
        Run(output="Failed to run clean test\n", rc=1, plain_rc=0),
        "skip",
        0,
    ),
    (
        "clean-run-really-broken",
        Run(output="Failed to run clean test\n", rc=1, plain_rc=1),
        "error",
        1,
    ),
    (
        "tracer-limitation",
        Run(output="BadTestExecutionCommandsException\n", rc=1, mutants=STATS, plain_rc=0),
        "skip",
        0,
    ),
    (
        "bad-test-command",
        Run(output="BadTestExecutionCommandsException\n", rc=1, mutants=STATS, plain_rc=1),
        "error",
        1,
    ),
    (
        "import-time-self-call",
        Run(output="No such file or directory: '<frozen importlib._bootstrap>'\n", rc=1),
        "skip",
        0,
    ),
    (
        "nonzero-exit-after-mutants-ran",
        Run(output="loguru teardown crash\n", rc=1, mutants=STATS, results={KILLED: "killed"}),
        "pass",
        0,
    ),
    ("results-unreadable", Run(results={KILLED: "killed"}, results_rc=1), "error", 1),
    ("run-interrupted", Run(results={KILLED: "killed", OTHER: "not checked"}), "error", 1),
    ("child-segfaulted", Run(results={KILLED: "killed", OTHER: "segfault"}), "error", 1),
    (
        "status-outside-every-bucket",
        Run(results={KILLED: "killed", OTHER: "check was interrupted by user"}),
        "error",
        1,
    ),
    (
        "proved-nothing",
        Run(results={KILLED: "suspicious", OTHER: "no tests"}),
        "error",
        1,
    ),
    (
        "chromadb-fork-crash",
        Run(
            output="    worker exit code -5\n    worker exit code -5\n",
            results={KILLED: "suspicious", OTHER: "suspicious"},
            mutants={f"{MODULE}.meta": _meta({KILLED: -5, OTHER: -5})},
        ),
        "skip",
        0,
    ),
    (
        "chromadb-fork-deadlock",
        Run(
            output="    worker exit code -24\n    worker exit code -24\n",
            results={KILLED: "timeout", OTHER: "timeout"},
            mutants={f"{MODULE}.meta": _meta({KILLED: -24, OTHER: -24})},
        ),
        "skip",
        0,
    ),
]


@pytest.mark.parametrize(
    ("run", "status", "returncode"),
    [pytest.param(run, status, rc, id=name) for name, run, status, rc in OUTCOMES],
)
def test_the_gate_reads_each_mutmut_outcome_as(
    tmp_path: Path, run: Run, status: str, returncode: int
) -> None:
    outcome = _shard(tmp_path, run)
    assert (outcome.status, outcome.returncode) == (status, returncode), outcome.output


def test_a_surviving_line_is_a_finding_on_that_line(tmp_path: Path) -> None:
    outcome = _shard(tmp_path, Run(results=SURVIVOR, classify={OTHER: "CHANGED:2"}))
    findings = outcome.verdict["findings"]
    assert isinstance(findings, list)
    assert [f["line"] for f in findings] == [2]
    assert "MUTATION FAILED" in outcome.output


def test_a_no_state_run_says_how_many_tests_timed_out(tmp_path: Path) -> None:
    outcome = _shard(
        tmp_path,
        Run(
            output="FAILED tests/unit/test_x.py::test_t - Failed: Timeout (>120.0s)\n",
            rc=1,
            mutants={"x": ""},
        ),
    )
    assert "1 test(s) hit the 120s per-test timeout" in str(outcome.verdict["summary"])
    # `mise ci:remote` reads this exact line out of the shard log artifact.
    assert "MUTATION RUN FAILED (no state produced)" in outcome.output


def test_a_skip_carries_its_reason(tmp_path: Path) -> None:
    outcome = _shard(tmp_path, Run(output="could not find any test case for any mutant\n", rc=1))
    assert "nothing on the changed lines for a test to pin" in str(outcome.verdict["summary"])


@pytest.mark.parametrize(
    ("ranges", "testfiles"),
    [
        pytest.param("[]", '["tests/unit/test_x.py"]', id="empty-line-scope"),
        pytest.param("[[2,2]]", '["tests/unit/test_missing.py"]', id="missing-test-file"),
    ],
)
def test_a_module_that_refuses_to_run_is_an_error(
    tmp_path: Path, ranges: str, testfiles: str
) -> None:
    root = _sandbox(tmp_path)
    group = json.dumps([{"module": MODULE, "testfiles": testfiles, "ranges": ranges}])
    result = subprocess.run(
        _command(root, "shard"),
        cwd=root,
        env=_env(tmp_path, GROUP=group, SHARD_LOG=str(root / "shard.log")),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert _verdict(tmp_path, MODULE)["status"] == "error"


def test_a_shard_reports_every_module_and_fails_on_any(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    second = "app/services/y.py"
    _write_scenario(tmp_path / "scenarios", MODULE, Run(results={KILLED: "killed"}))
    _write_scenario(
        tmp_path / "scenarios",
        second,
        Run(
            results={"app.services.y.x_total__mutmut_1": "survived"},
            classify={"app.services.y.x_total__mutmut_1": "CHANGED:2"},
        ),
    )
    result = subprocess.run(
        _command(root, "shard"),
        cwd=root,
        env=_env(tmp_path, GROUP=_group(MODULE, second), SHARD_LOG=str(root / "shard.log")),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert _verdict(tmp_path, MODULE)["status"] == "pass"
    assert _verdict(tmp_path, second)["status"] == "fail"
    assert f"mutation failed for: {second}" in result.stdout
    replay = json.loads((root / "shard.verdict.json").read_text())
    assert [m["module"] for m in replay["modules"]] == [MODULE, second]


def test_local_runs_each_module_as_its_own_shard_and_summarises(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    second = "app/services/y.py"
    _write_scenario(tmp_path / "scenarios", MODULE, Run(results={KILLED: "killed"}))
    _write_scenario(
        tmp_path / "scenarios",
        second,
        Run(
            results={"app.services.y.x_total__mutmut_1": "survived"},
            classify={"app.services.y.x_total__mutmut_1": "CHANGED:2"},
        ),
    )
    matrix = [
        {
            "module": m,
            "testfiles": [f"tests/unit/test_{Path(m).stem}.py"],
            "changed_lines": [[2, 2]],
        }
        for m in (MODULE, second)
    ]
    detector = root / "scripts" / "ci" / "lib" / "mutation_matrix.py"
    detector.write_text(f"import sys\nsys.stdin.read()\nprint({json.dumps(json.dumps(matrix))})\n")
    result = subprocess.run(
        [*_command(root, "local"), MODULE, second],
        cwd=root,
        env=_env(tmp_path, MUTATION_JOBS="2", MUTMUT_MAX_CHILDREN="1"),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"  pass      {MODULE}" in result.stdout
    assert f"  SURVIVORS {second}" in result.stdout
    assert "module(s) with survivors on changed lines" in result.stdout


# --- behaviour the rewrite changed, each a bug -------------------------------


def test_a_mutant_timeout_is_not_mistaken_for_the_chromadb_fork_crash(tmp_path: Path) -> None:
    """One mutant killed at its CPU limit (-24) must not skip a module nothing graded.

    The carve-out matched "worker exit code -5|-24" anywhere in the log, and -24
    is every Linux mutant timeout, so one timeout beside uncovered mutants
    skipped green instead of failing as proving nothing.
    """
    outcome = _shard(
        tmp_path,
        Run(
            output="    worker exit code -24\n",
            results={KILLED: "no tests", OTHER: "timeout"},
            mutants={f"{MODULE}.meta": _meta({KILLED: 33, OTHER: -24})},
        ),
    )
    assert (outcome.status, outcome.returncode) == ("error", 1), outcome.output


def test_a_module_whose_every_mutant_hangs_a_test_is_not_the_fork_crash(tmp_path: Path) -> None:
    """Every mutant killed at -24 inside a test body is a real timeout, not a skip.

    -24 is both the chromadb deadlock and mutmut's own timeout, so exit codes
    alone skipped green a module whose mutants all hung its tests.
    """
    test = "tests/unit/test_x.py::test_t"
    outcome = _shard(
        tmp_path,
        Run(
            output="    worker exit code -24\n    worker exit code -24\n",
            results={KILLED: "timeout", OTHER: "timeout"},
            mutants={f"{MODULE}.meta": _meta({KILLED: -24, OTHER: -24})},
            killed_in_test={KILLED: test, OTHER: test},
        ),
    )
    assert (outcome.status, outcome.returncode) == ("error", 1), outcome.output
    assert f"killed inside a test body (first: {KILLED} in {test})" in outcome.output


def test_the_in_test_marker_survives_only_a_child_killed_inside_a_test_body(
    tmp_path: Path,
) -> None:
    """The real plugin: a test that returns or fails clears its marker, one killed mid-body keeps it."""
    (tmp_path / "test_m.py").write_text(
        "import os\n\n"
        "def test_passes():\n    assert True\n\n"
        "def test_fails():\n    assert False\n\n"
        "def test_killed():\n    os._exit(9)\n"
    )
    markers = tmp_path / "in-test"
    markers.mkdir()
    env = {
        **os.environ,
        "PYTHONPATH": str(CI.parent / "test"),
        "MUTMUT_IN_TEST_DIR": str(markers),
        "MUTANT_UNDER_TEST": KILLED,
    }
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-p", "no:cacheprovider"]
    command += ["-p", "mutmut_in_test_marker", "test_m.py"]
    run = subprocess.run(
        command, cwd=tmp_path, env=env, capture_output=True, text=True, check=False
    )
    assert run.returncode == 9, run.stdout + run.stderr
    assert {p.name: p.read_text() for p in markers.iterdir()} == {KILLED: "test_m.py::test_killed"}


def test_a_line_that_is_not_a_mutant_does_not_make_a_run_incomplete(tmp_path: Path) -> None:
    """Every stdout line of `mutmut results` counted as a mutant, so a banner failed a graded run."""
    outcome = _shard(
        tmp_path,
        Run(raw_results="mutmut: using cached stats\n" + _results({KILLED: "killed"})),
    )
    assert (outcome.status, outcome.returncode) == ("pass", 0), outcome.output


def test_a_group_whose_testfiles_is_not_a_path_list_is_unreadable(tmp_path: Path) -> None:
    """The GROUP is typed at the boundary: a malformed entry stops the shard before any module.

    It used to reach the module as an argument and fail there, one module at a
    time; the plan never emits one, so either way it is a broken plan job.
    """
    root = _sandbox(tmp_path)
    group = json.dumps([{"module": MODULE, "testfiles": '"tests/unit/test_x.py"', "ranges": "[]"}])
    result = subprocess.run(
        _command(root, "shard"),
        cwd=root,
        env=_env(tmp_path, GROUP=group, SHARD_LOG=str(root / "shard.log")),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 1
    assert "could not read its GROUP" in result.stdout
