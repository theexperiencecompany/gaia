"""The mutation gate's verdict artifact (scripts/ci/lib/mutation_report.py).

What this covers is the difference between a lane you can act on and one you
cannot. A shard log is 25k-190k lines; the verdict is the last hundred, and it
used to be a list of mutant NAMES with at most 40 diffs — so a survivor past
the cap carried a name and nothing else, and mutmut's numbering depends on the
diff scope, which means that name cannot be regenerated on a laptop. Every
assertion here is about that gap closing: the full diff reaching the verdict
file, the survivors grouping by source line, the annotation landing on the PR
diff, `replay` reproducing one survivor without touching the working tree — and
a run that proved nothing never reporting a pass.

Driven as real subprocess runs. The survivor fixtures are trimmed excerpts of a
genuine shard log (PR #1161, mutation-log-2), not hand-written approximations
of one — the parser's whole job is to read what mutmut actually prints.
"""

from collections.abc import Iterator
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT = REPO_ROOT / "scripts" / "ci" / "lib" / "mutation_report.py"
MUTATION_SH = REPO_ROOT / "scripts" / "ci" / "mutation.sh"
LOG_LIB = REPO_ROOT / "scripts" / "ci" / "lib" / "log.sh"
CPU_SLOTS_LIB = REPO_ROOT / "scripts" / "ci" / "lib" / "cpu-slots.sh"
FIXTURES = Path(__file__).parent / "fixtures"
# .txt, not .log: the repo .gitignore has a blanket `*.log`, which would
# silently leave these fixtures out of the commit and red the suite on a fresh
# clone. The content is a verbatim shard-log excerpt either way.
SURVIVOR_LOG = FIXTURES / "mutation_shard_survivors.txt"
SKIP_LOG = FIXTURES / "mutation_shard_skip.txt"

# The survivors the grouping tests key on, and the source line each one mutates
# as `mutation_classify.py` resolved it against the real module.
BOT_MODULE = "app/api/v1/endpoints/bot.py"
BOT_SLUG = "app_api_v1_endpoints_bot"
BOT_PREFIX = "app.api.v1.endpoints.bot.x__may_mint_bot_upgrade_link__mutmut_"
BOT_SOURCE = '''def _may_mint_bot_upgrade_link(user_id: str) -> bool:
    """Claim the once-a-day window."""
    try:
        claimed = await redis_cache.client.set(
            f"{BOT_UPGRADE_LINK_PREFIX}{user_id}", "1", nx=True, ex=BOT_UPGRADE_LINK_TTL
        )
    except Exception as e:
        log.warning("unavailable", error=str(e))
    return bool(claimed)
'''
BOT_ARGS_LINE = 5


def _run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPORT), *args],
        capture_output=True,
        text=True,
        check=False,
        **kwargs,
    )


def _records(tmp_path: Path, rows: list[tuple[str, str, str]]) -> Path:
    path = tmp_path / "records.tsv"
    path.write_text("".join("\t".join(row) + "\n" for row in rows))
    return path


def _module_record(
    tmp_path: Path, rows: list[tuple[str, str, str]], status: str = "survivors"
) -> dict[str, object]:
    """Run the `module` subcommand over the real fixture diffs and read it back."""
    module_file = tmp_path / "bot.py"
    module_file.write_text(BOT_SOURCE)
    out = tmp_path / "records" / f"{BOT_SLUG}.json"
    result = _run(
        [
            "module",
            "--module",
            BOT_MODULE,
            "--path",
            f"apps/api/{BOT_MODULE}",
            "--module-file",
            str(module_file),
            "--records",
            str(_records(tmp_path, rows)),
            "--diffs",
            str(SURVIVOR_LOG),
            "--testfiles",
            '["tests/unit/api/test_bot_endpoint.py"]',
            "--status",
            status,
            "--out",
            str(out),
        ]
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text())
    data["_report"] = result.stdout
    return data


def test_the_module_record_carries_every_survivor_with_its_full_diff(tmp_path: Path) -> None:
    """This lane's own record: one entry per MUTANT, each with the WHOLE diff.

    The diff is the record's reason to exist — a mutant id alone is unactionable
    because mutmut's numbering cannot be regenerated outside the run that
    produced it — and this file, not the shared verdict, is what `replay` reads.
    """
    rows = [(f"{BOT_PREFIX}{n}", "survived", f"CHANGED:{BOT_ARGS_LINE}") for n in (3, 4, 5)]
    record = _module_record(tmp_path, rows)

    assert record["module"] == BOT_MODULE
    assert record["status"] == "survivors"
    assert record["testfiles"] == ["tests/unit/api/test_bot_endpoint.py"]
    survivors = record["survivors"]
    assert [entry["name"] for entry in survivors] == [row[0] for row in rows]
    for entry in survivors:
        assert entry["function"] == "_may_mint_bot_upgrade_link"
        assert entry["line"] == BOT_ARGS_LINE
        assert entry["source"].startswith('f"{BOT_UPGRADE_LINK_PREFIX}{user_id}", "1"')
        assert entry["diff"].startswith("--- app/api/v1/endpoints/bot.py")
        assert '+            f"{BOT_UPGRADE_LINK_PREFIX}{user_id}"' in entry["diff"]
    assert [entry["change"] for entry in survivors] == [
        '"1" → None',
        "nx=True → nx=None",
        "ex=BOT_UPGRADE_LINK_TTL → ex=None",
    ]


def test_the_record_is_not_written_into_the_verdict_tree(tmp_path: Path) -> None:
    """Nothing but `verdict.py emit` output may live under verify-logs/verdicts.

    `consolidate` reads every JSON in that tree and indexes `doc["lane"]`; a
    file of a different shape there does not degrade, it crashes the gate.
    """
    rows = [(f"{BOT_PREFIX}3", "survived", f"CHANGED:{BOT_ARGS_LINE}")]
    record = _module_record(tmp_path, rows)
    record.pop("_report")
    assert "lane" not in record
    assert not (tmp_path / "verify-logs").exists()


def test_excluded_survivors_stay_visible_in_the_record(tmp_path: Path) -> None:
    """A logging-only or equivalent mutant is kept, with why — never dropped."""
    record = _module_record(
        tmp_path,
        [
            (f"{BOT_PREFIX}3", "survived", f"CHANGED:{BOT_ARGS_LINE}"),
            (f"{BOT_PREFIX}4", "survived", "LOGGING:8"),
            (f"{BOT_PREFIX}5", "survived", "EQUIV"),
            (f"{BOT_PREFIX}7", "survived", "UNCHANGED:9"),
        ],
    )
    assert len(record["survivors"]) == 1
    excluded = {entry["name"]: entry["reason"] for entry in record["excluded"]}
    assert set(excluded) == {f"{BOT_PREFIX}{n}" for n in (4, 5, 7)}
    assert "logging-only" in excluded[f"{BOT_PREFIX}4"]
    report = str(record["_report"])
    assert "3 survivor(s) excluded from the verdict" in report
    assert "provably equivalent" in report


def test_a_clean_module_still_records(tmp_path: Path) -> None:
    """`pass` is a fact the gate must read, not an absence it has to infer."""
    record = _module_record(tmp_path, [], status="pass")
    assert record["status"] == "pass"
    assert record["survivors"] == []


def test_report_groups_mutants_under_one_source_line(tmp_path: Path) -> None:
    """Eight mutants on one line read as one heading, not eight mutmut names."""
    rows = [
        (f"{BOT_PREFIX}{n}", "survived", f"CHANGED:{BOT_ARGS_LINE}")
        for n in (3, 4, 5, 7, 8, 9, 10, 11)
    ]
    report = str(_module_record(tmp_path, rows)["_report"])

    assert f"apps/api/{BOT_MODULE}:{BOT_ARGS_LINE}" in report
    assert "8 mutant(s) survive on this line" in report
    assert report.count(f"apps/api/{BOT_MODULE}:") == 1
    assert "8 surviving mutant(s) on 1 changed line(s)" in report
    # The source line itself, so the reader never has to open the file.
    assert 'f"{BOT_UPGRADE_LINK_PREFIX}{user_id}", "1", nx=True' in report
    # Each mutant still names its own edit, in words rather than in mutant ids.
    assert '"1" → None' in report
    assert "nx=True → nx=None" in report
    assert "mutation.sh replay" in report


def test_report_splits_distinct_lines(tmp_path: Path) -> None:
    """Two mutated lines are two headings, ordered by line number."""
    report = str(
        _module_record(
            tmp_path,
            [
                (f"{BOT_PREFIX}9", "survived", "CHANGED:8"),
                (f"{BOT_PREFIX}3", "survived", f"CHANGED:{BOT_ARGS_LINE}"),
            ],
        )["_report"]
    )
    first = report.index(f"apps/api/{BOT_MODULE}:{BOT_ARGS_LINE}")
    second = report.index(f"apps/api/{BOT_MODULE}:8")
    assert first < second, "surviving lines must be listed in file order"


# --- collect -----------------------------------------------------------------


def _collect(
    tmp_path: Path, log: Path, rcs: list[tuple[str, str]]
) -> tuple[str, dict[str, object], dict[str, dict[str, object]]]:
    """Run `collect` for real, and read back BOTH artifacts it produces.

    Returns (output, shard.verdict.json, {lane: shared verdict}). The shared
    verdicts come from the real `verdict.py emit` — stubbing the one producer
    would prove only that this file can call a stub.
    """
    rcs_file = tmp_path / "rcs.tsv"
    rcs_file.write_text("".join(f"{module}\t{rc}\n" for module, rc in rcs))
    records = tmp_path / "records"
    records.mkdir(exist_ok=True)
    shard_verdict = tmp_path / "shard.verdict.json"
    verdicts = tmp_path / "verdicts"
    summary = tmp_path / "summary.md"
    summary.touch()
    result = subprocess.run(
        [
            sys.executable,
            str(REPORT),
            "collect",
            "--log",
            str(log),
            "--dir",
            str(records),
            "--rcs",
            str(rcs_file),
            "--out",
            str(shard_verdict),
            "--repo-root",
            str(REPO_ROOT),
            "--verdict-out",
            str(verdicts),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_isolated_env(tmp_path, GITHUB_STEP_SUMMARY=str(summary)),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    _assert_nothing_escaped(tmp_path)
    emitted = {
        json.loads(path.read_text())["lane"]: json.loads(path.read_text())
        for path in verdicts.rglob("*.json")
    }
    output = result.stdout + result.stderr + summary.read_text()
    return output, json.loads(shard_verdict.read_text()), emitted


def test_collect_reports_each_module_through_the_shared_producer(tmp_path: Path) -> None:
    """One lane verdict per module, in the shape the quality gate consolidates.

    Written by `verdict.py emit`, not by this lane: `emit` is the contract's
    only producer, and it is what keeps the file, the annotation and the
    step-summary block from drifting apart.
    """
    rows = [(f"{BOT_PREFIX}{n}", "survived", f"CHANGED:{BOT_ARGS_LINE}") for n in (3, 4)]
    # `module` writes its record into the very directory `collect` reads.
    _module_record(tmp_path, rows)
    _output, _shard, emitted = _collect(tmp_path, SURVIVOR_LOG, [(BOT_MODULE, "1")])

    verdict = emitted[f"mutation/{BOT_MODULE}"]
    assert set(verdict) == {"lane", "status", "summary", "findings", "advice"}
    assert verdict["status"] == "fail"
    assert "2 surviving mutant(s) on 1 changed line(s)" in str(verdict["summary"])


def test_collect_emits_one_finding_per_surviving_line(tmp_path: Path) -> None:
    """The shared verdict groups by LINE; the mutant-level record stays ours.

    One entry per thing to fix on the gate's table and on the PR's diff — eight
    findings on one line would be eight copies of the same finding.
    """
    rows = [
        (f"{BOT_PREFIX}{n}", "survived", f"CHANGED:{BOT_ARGS_LINE}")
        for n in (3, 4, 5, 7, 8, 9, 10, 11)
    ]
    _module_record(tmp_path, rows)
    output, shard, emitted = _collect(tmp_path, SURVIVOR_LOG, [(BOT_MODULE, "1")])

    findings = emitted[f"mutation/{BOT_MODULE}"]["findings"]
    assert len(findings) == 1
    assert findings[0]["file"] == f"apps/api/{BOT_MODULE}"
    assert findings[0]["line"] == BOT_ARGS_LINE
    assert findings[0]["message"].startswith("8 mutant(s) survive: ")
    assert '"1" → None; nx=True → nx=None' in findings[0]["message"]
    # The detail is every diff on that line, so the finding is self-contained.
    assert findings[0]["detail"].count("--- app/api/v1/endpoints/bot.py") == 8
    # And the mutant-level record is still there, in the replay artifact.
    assert len(shard["modules"][0]["survivors"]) == 8


def test_collect_annotates_once_per_line_through_emit(tmp_path: Path) -> None:
    """`emit` prints the annotations — this lane must not print them again."""
    rows = [(f"{BOT_PREFIX}{n}", "survived", f"CHANGED:{BOT_ARGS_LINE}") for n in (3, 4)]
    _module_record(tmp_path, rows)
    output, _shard, _emitted = _collect(tmp_path, SURVIVOR_LOG, [(BOT_MODULE, "1")])

    annotations = [line for line in output.splitlines() if line.startswith("::error file=")]
    assert len(annotations) == 1
    assert annotations[0].startswith(f"::error file=apps/api/{BOT_MODULE},line={BOT_ARGS_LINE}::")
    assert "2 mutant(s) survive" in annotations[0]
    assert "\n" not in annotations[0]


def test_collect_advice_points_at_the_replay_artifact(tmp_path: Path) -> None:
    """The advice is a command, and it names the file that can actually run it."""
    rows = [(f"{BOT_PREFIX}3", "survived", f"CHANGED:{BOT_ARGS_LINE}")]
    _module_record(tmp_path, rows)
    _output, _shard, emitted = _collect(tmp_path, SURVIVOR_LOG, [(BOT_MODULE, "1")])

    advice = [str(item) for item in emitted[f"mutation/{BOT_MODULE}"]["advice"]]
    assert any(f"apps/api/{BOT_MODULE}:{BOT_ARGS_LINE}" in item for item in advice)
    replay = next(item for item in advice if "mutation.sh replay" in item)
    assert "shard.verdict.json" in replay
    assert "verify-logs/verdicts" not in replay


def test_collect_rebuilds_a_module_that_wrote_no_record(tmp_path: Path) -> None:
    """A module killed mid-run still reaches the gate, read off its log."""
    _output, shard, emitted = _collect(tmp_path, SURVIVOR_LOG, [(BOT_MODULE, "1")])
    assert emitted[f"mutation/{BOT_MODULE}"]["status"] == "fail"
    # Every diff the log carried, recovered — the cap is gone from both sides.
    survivors = shard["modules"][0]["survivors"]
    assert len(survivors) == 8
    assert all(entry["diff"] for entry in survivors)


def test_collect_reads_a_skip_as_a_skip_with_its_reason(tmp_path: Path) -> None:
    """A skipped module is `skip`, not `pass` and not `error`."""
    module = "app/agents/tools/workflow_shared_tools.py"
    _output, _shard, emitted = _collect(tmp_path, SKIP_LOG, [(module, "0")])
    verdict = emitted[f"mutation/{module}"]
    assert verdict["status"] == "skip"
    assert "no mutant had covering tests" in str(verdict["summary"])
    assert verdict["findings"] == []


def test_collect_reads_the_no_test_gap_as_a_failure(tmp_path: Path) -> None:
    """Changed lines no test reaches are a `fail` with one finding per line.

    No diff exists for them — mutmut never generated a mutant for a line
    nothing covers — so the message carries the whole finding.
    """
    log = tmp_path / "shard.log"
    log.write_text(
        "=== app/services/x.py ===\n"
        "mutating app/services/x.py (tests: tests/unit/test_x.py) ...\n"
        "MUTATION FAILED — changed code no test reaches in app/services/x.py:\n"
        "      line(s) 12 13 40\n"
    )
    output, _shard, emitted = _collect(tmp_path, log, [("app/services/x.py", "1")])
    verdict = emitted["mutation/app/services/x.py"]
    assert verdict["status"] == "fail"
    assert "3 changed line(s) no test reaches" in str(verdict["summary"])
    assert [finding["line"] for finding in verdict["findings"]] == [12, 13, 40]
    assert all("no mapped test executes" in f["message"] for f in verdict["findings"])
    assert any("Write a test that executes" in str(item) for item in verdict["advice"])
    assert output.count("::error file=apps/api/app/services/x.py,line=") == 3


def test_collect_lets_a_nonzero_exit_beat_an_inconclusive_log(tmp_path: Path) -> None:
    """A module that exited non-zero is never reported as a pass.

    An inconclusive section read as `pass` is exactly the silence-read-as-success
    this gate exists to stop.
    """
    log = tmp_path / "shard.log"
    log.write_text("=== app/services/x.py ===\nmutating app/services/x.py (tests: t.py) ...\n")
    _output, _shard, emitted = _collect(tmp_path, log, [("app/services/x.py", "1")])
    assert emitted["mutation/app/services/x.py"]["status"] == "error"


def test_collect_reads_a_killed_module_as_timed_out(tmp_path: Path) -> None:
    """124/137 is the watchdog, not a test weakness — and not a pass either."""
    log = tmp_path / "shard.log"
    log.write_text("=== app/services/x.py ===\nMutation: OK — no survivors\n")
    _output, _shard, emitted = _collect(tmp_path, log, [("app/services/x.py", "137")])
    verdict = emitted["mutation/app/services/x.py"]
    assert verdict["status"] == "timed_out"
    assert "killed at its timeout" in str(verdict["summary"])


def test_collect_summary_counts_modules_without_repeating_findings(tmp_path: Path) -> None:
    """The shard's block is a roll-up; `emit` already wrote every finding."""
    output, _shard, _emitted = _collect(tmp_path, SURVIVOR_LOG, [(BOT_MODULE, "1")])
    assert "| status | modules |" in output
    assert "| survivors | 1 |" in output


# --- driven end to end through mutation.sh shard -----------------------------


def _sandbox(tmp_path: Path, mutmut_behaviour: str) -> Path:
    """A miniature repo `mutation.sh shard` can run for real, end to end.

    The fake venv python is the point: it answers the mutmut invocations the way
    a broken (or empty) run does and hands everything else to the real
    interpreter, so the shard, the report, `verdict.py emit` and `consolidate`
    all run as themselves. mutmut against the real apps/api is far too heavy for
    a laptop, and the failures under test are precisely the ones where mutmut
    produces nothing.
    """
    root = tmp_path / "repo"
    api = root / "apps" / "api"
    (api / "app" / "services").mkdir(parents=True)
    (api / "tests" / "unit").mkdir(parents=True)
    (api / "scripts").mkdir(parents=True)
    (api / "app" / "services" / "x.py").write_text("def total(a, b):\n    return a + b\n")
    (api / "tests" / "unit" / "test_x.py").write_text("def test_nothing():\n    assert True\n")
    (api / "pyproject.toml").write_text('[tool.mutmut]\nsource_paths = ["app"]\n')
    (api / "pytest.ini").write_text("[pytest]\n")

    scripts_ci = root / "scripts" / "ci"
    (scripts_ci / "lib").mkdir(parents=True)
    for source, name in (
        (MUTATION_SH, "mutation.sh"),
        (REPO_ROOT / "scripts" / "ci" / "verdict.py", "verdict.py"),
        (LOG_LIB, "lib/log.sh"),
        (CPU_SLOTS_LIB, "lib/cpu-slots.sh"),
        (REPO_ROOT / "scripts" / "ci" / "lib" / "mutation_gap.py", "lib/mutation_gap.py"),
        (REPORT, "lib/mutation_report.py"),
    ):
        (scripts_ci / name).write_bytes(source.read_bytes())

    venv_python = root / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        # The mutmut child: `python -c <program> <patch-dir>`.
        f"  -c*) {mutmut_behaviour} ;;\n"
        # `-m mutmut results --all True` — no results at all. Anchored on the
        # whole invocation, not on `*mutmut*`: the verdict call carries the word
        # in its --reason text, and a looser pattern swallowed it here.
        '  "-m mutmut"*) exit 0 ;;\n'
        # `lib/mutation_gap.py <module> <ranges>` — the gap classifier asks
        # mutmut (with the lane's patches) which changed lines can host a
        # mutant, so it needs the API venv, which this fake stands in for.
        # Line 2 of the sandbox module is the one answer these tests rely on;
        # the classifier's own correctness is proven with real mutmut in
        # apps/api/tests/unit/scripts/test_mutation_gap.py.
        "  *lib/mutation_gap.py*) echo 2 ;;\n"
        f'  *) exec {sys.executable} "$@" ;;\n'
        "esac\n"
    )
    venv_python.chmod(0o755)
    return root


# The repo's own verdict tree. Nothing in this file may create it: whatever
# lands there is uploaded by the lane's composite and consolidated by the
# quality gate as a REAL lane — a test fixture named `app/does_not_exist.py`
# surfaced on the gate of run 34586506166 exactly that way.
REPO_VERDICTS = REPO_ROOT / "verify-logs" / "verdicts"


def _isolated_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    """The environment every emitting subprocess runs in.

    `verdict.py emit` resolves its output directory as
    `--out > $GAIA_VERDICT_DIR > $RUNNER_TEMP/verdicts > verify-logs/verdicts`,
    so a test that sets neither writes a REAL lane verdict — into the job's
    upload directory on a runner, into the checkout on a laptop. RUNNER_TEMP is
    pointed at a disposable path too, and asserted empty afterwards, so the
    override is shown to be what is doing the work.
    """
    return {
        **os.environ,
        "GAIA_VERDICT_DIR": str(tmp_path / "verdicts"),
        "RUNNER_TEMP": str(tmp_path / "runner-temp"),
        **extra,
    }


def _assert_nothing_escaped(tmp_path: Path) -> None:
    """Neither fallback directory received a verdict from this test."""
    runner_verdicts = tmp_path / "runner-temp" / "verdicts"
    assert not runner_verdicts.exists(), sorted(runner_verdicts.rglob("*"))


def _assert_repo_verdicts_untouched(before: set[Path]) -> None:
    """The repo's verdict tree is not a test output directory.

    Checked by path rather than by `git status`, which is blind here:
    verify-logs/ is gitignored, so a verdict written into the checkout is
    invisible to git and visible to the gate — the worst way round.
    """
    after = set(REPO_VERDICTS.rglob("*")) if REPO_VERDICTS.exists() else set()
    assert after == before, f"the test wrote into the repo's verdict tree: {after - before}"


@pytest.fixture(autouse=True)
def repo_verdicts_untouched() -> Iterator[None]:
    """Applies the guard to every test in this file, including future ones."""
    before = set(REPO_VERDICTS.rglob("*")) if REPO_VERDICTS.exists() else set()
    yield
    _assert_repo_verdicts_untouched(before)


def _run_shard(root: Path, module: str = "app/services/x.py") -> subprocess.CompletedProcess[str]:
    group = json.dumps(
        [{"module": module, "testfiles": '["tests/unit/test_x.py"]', "ranges": "[[2,2]]"}]
    )
    return subprocess.run(
        ["bash", str(root / "scripts" / "ci" / "mutation.sh"), "shard"],
        capture_output=True,
        text=True,
        check=False,
        cwd=root,
        env=_isolated_env(root, GROUP=group, SHARD_LOG=str(root / "shard.log")),
    )


def _consolidate(root: Path, expect: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "ci" / "verdict.py"),
            "consolidate",
            str(root / "verdicts"),
            "--expect",
            expect,
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=root,
    )


def test_a_mutmut_child_that_produced_nothing_is_an_error_not_a_pass(tmp_path: Path) -> None:
    """No results + empty log + no mutants/ must never read as "Mutation: OK".

    This shipped: a stray double quote in a comment inside the bash-quoted
    python program truncated it, so the child exited 0 having printed nothing,
    `mutmut results` returned empty, every TOTAL>0 guard was skipped, and every
    module in the lane reported OK for a day while mutmut never ran.
    """
    root = _sandbox(tmp_path, "exit 0")
    result = _run_shard(root)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "MUTATION RUN PRODUCED NO RESULTS" in result.stdout
    assert "Mutation: OK" not in result.stdout
    verdict = json.loads((root / "verdicts/mutation/app/services/x.py.json").read_text())
    assert verdict["lane"] == "mutation/app/services/x.py"
    assert verdict["status"] == "error"
    assert verdict["summary"] == "mutmut produced no results — the child did not run"


def test_a_run_that_generated_no_mutants_is_a_skip_not_a_pass(tmp_path: Path) -> None:
    """mutmut ran and found nothing to mutate: honest, but still not proof.

    Distinguished from the case above by the evidence that it ran at all — a
    log with output in it and a mutants/ tree on disk.
    """
    root = _sandbox(tmp_path, "echo 'Generating mutants'; mkdir -p mutants; exit 0")
    result = _run_shard(root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Mutation: OK" not in result.stdout
    assert "generated no mutants" in result.stdout
    verdict = json.loads((root / "verdicts/mutation/app/services/x.py.json").read_text())
    assert verdict["status"] == "skip"
    assert "generated no mutants" in verdict["summary"]


def test_a_module_no_test_reaches_fails_the_gate(tmp_path: Path) -> None:
    """The gap branch, end to end: mutmut found no covering test for any mutant.

    `lib/mutation_gap.py` decides whether that means "nothing mutatable here"
    (a skip) or "executable code nothing runs" (a failure). Line 2 of the
    sandbox module is a return statement no test executes, so it is the latter.
    """
    root = _sandbox(
        tmp_path, "echo 'could not find any test case for any mutant'; mkdir -p mutants; exit 1"
    )
    result = _run_shard(root)

    assert result.returncode != 0, result.stdout + result.stderr
    verdict = json.loads((root / "verdicts/mutation/app/services/x.py.json").read_text())
    assert verdict["status"] == "fail"
    assert "no test reaches" in verdict["summary"]
    assert [finding["line"] for finding in verdict["findings"]] == [2]
    assert any("Write a test that executes" in str(item) for item in verdict["advice"])


def test_the_gate_consolidates_the_mutation_family_and_fails_on_it(tmp_path: Path) -> None:
    """The whole point of the shared schema: `consolidate` sees this lane.

    `test-mutation@mutation` is the gate's own mapping — the job is
    `test-mutation`, the lane family is `mutation`, and the family is satisfied
    by any `mutation/...` verdict, because how many modules there are is decided
    by `mutation.sh plan` at runtime.
    """
    root = _sandbox(tmp_path, "exit 0")
    _run_shard(root)
    result = _consolidate(root, "test-mutation@mutation=success")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "mutation/app/services/x.py" in result.stdout
    assert "ERROR" in result.stdout.upper()


def test_the_gate_passes_when_every_module_is_clean(tmp_path: Path) -> None:
    """A skip is not a failure: the family reported, and nothing was wrong."""
    root = _sandbox(tmp_path, "echo 'Generating mutants'; mkdir -p mutants; exit 0")
    _run_shard(root)
    result = _consolidate(root, "test-mutation@mutation=success")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "mutation/app/services/x.py" in result.stdout


def _shard_with_env(root: Path, **env: str) -> subprocess.CompletedProcess[str]:
    """Drive the shard with an explicit environment, nothing inherited but PATH."""
    group = json.dumps(
        [
            {
                "module": "app/services/x.py",
                "testfiles": '["tests/unit/test_x.py"]',
                "ranges": "[[2,2]]",
            }
        ]
    )
    return subprocess.run(
        ["bash", str(root / "scripts" / "ci" / "mutation.sh"), "shard"],
        capture_output=True,
        text=True,
        check=False,
        cwd=root,
        env={**os.environ, "GROUP": group, "SHARD_LOG": str(root / "shard.log"), **env},
    )


def test_the_shard_takes_its_cpu_tokens_from_a_private_pool_never_the_host(
    tmp_path: Path, flock: str
) -> None:
    """A shard acquires nproc-2 host CPU tokens before its first module. Run on
    the box with the pool inherited, this suite queued behind the real shards
    for the semaphore's full 600 s fail-open wait — per test — and the harness
    lane died at its cap with the last 6% never reached (job 103243166187).
    conftest.py points every test at a pool of its own; this proves the shard
    honours it: its grant lands there, and is gone again when it exits.

    The verdict is the same story one rung over: the first run of this test
    inherited the job's RUNNER_TEMP, the shard wrote `mutation/app/services/
    x.py` into the job's real verdict directory, and the harness job's
    ownership check refused to upload a lane it does not own (run 34595547568).
    """
    root = _sandbox(tmp_path, "exit 0")
    pool = Path(os.environ["GAIA_CPU_SLOTS_DIR"])
    job_temp = tmp_path / "job-runner-temp"

    # The fake mutmut yields nothing, so the module fails on the zero-output
    # guard; the tokens are taken before that and released after regardless.
    result = _shard_with_env(root, RUNNER_ENVIRONMENT="self-hosted", RUNNER_TEMP=str(job_temp))

    assert "cpu-slots" not in result.stdout + result.stderr, "the governor should be live and quiet"
    assert (pool / "holders").is_dir(), "the shard never touched the private pool"
    assert not list((pool / "holders").iterdir()), "a grant leaked past the shard's exit"
    assert not (job_temp / "verdicts").exists(), "the shard wrote into the job's own verdict dir"
    assert (Path(os.environ["GAIA_VERDICT_DIR"]) / "mutation").is_dir()


def test_the_shard_puts_verdicts_where_gaia_verdict_dir_says(tmp_path: Path) -> None:
    """The top rung: an explicit override beats everything below it."""
    root = _sandbox(tmp_path, "exit 0")
    chosen = tmp_path / "chosen" / "verdicts"
    runner_temp = tmp_path / "runner-temp"
    _shard_with_env(root, GAIA_VERDICT_DIR=str(chosen), RUNNER_TEMP=str(runner_temp))

    assert (chosen / "mutation" / "app" / "services" / "x.py.json").exists()
    assert not (runner_temp / "verdicts").exists()
    assert not (root / "verify-logs" / "verdicts").exists()


def test_the_shard_falls_back_to_the_runner_temp_rung(tmp_path: Path) -> None:
    """The CI rung, and the one a shell copy of the order got wrong.

    Nothing sets GAIA_VERDICT_DIR on a runner: `verdict.py` resolves
    `$RUNNER_TEMP/verdicts`, which is per-job, wiped between jobs, and where the
    upload composite and the gate both read. A mutation.sh that defaulted to the
    checkout instead would put every verdict somewhere the gate calls NO
    VERDICT — so this rung is asserted, not assumed.
    """
    root = _sandbox(tmp_path, "exit 0")
    runner_temp = tmp_path / "runner-temp"
    env = {key: value for key, value in os.environ.items() if key != "GAIA_VERDICT_DIR"}
    result = subprocess.run(
        ["bash", str(root / "scripts" / "ci" / "mutation.sh"), "shard"],
        capture_output=True,
        text=True,
        check=False,
        cwd=root,
        env={
            **env,
            "GROUP": json.dumps(
                [
                    {
                        "module": "app/services/x.py",
                        "testfiles": '["tests/unit/test_x.py"]',
                        "ranges": "[[2,2]]",
                    }
                ]
            ),
            "SHARD_LOG": str(root / "shard.log"),
            "RUNNER_TEMP": str(runner_temp),
        },
    )

    assert (runner_temp / "verdicts" / "mutation" / "app" / "services" / "x.py.json").exists(), (
        result.stdout + result.stderr
    )
    # Not the checkout default, which is the rung below this one.
    assert not (root / "verify-logs" / "verdicts").exists()


def test_the_shard_keeps_its_replay_artifact_out_of_the_verdict_tree(tmp_path: Path) -> None:
    """`consolidate` crashes on a foreign shape; only emit's output goes there."""
    root = _sandbox(tmp_path, "exit 0")
    _run_shard(root)

    assert (root / "shard.verdict.json").exists()
    for path in (root / "verdicts").rglob("*.json"):
        assert "lane" in json.loads(path.read_text()), f"{path} is not a lane verdict"


# --- replay ------------------------------------------------------------------

CALC_SOURCE = """def total(a, b):
    return a + b


def label(name):
    return "total: " + name
"""

CALC_TEST = """from app.calc import total


def test_total():
    assert total(2, 3) == 5
"""

MATRIX_STUB = """#!/usr/bin/env python3
import json

print(json.dumps([{"module": "app/calc.py", "testfiles": ["tests/test_calc.py"]}]))
"""


def _synthetic_repo(tmp_path: Path) -> Path:
    """A git repo with a tiny app/ + tests/ — mutmut against apps/api is far too
    heavy for a laptop, and replay's contract does not depend on the real API."""
    root = tmp_path / "repo"
    api = root / "apps" / "api"
    (api / "app").mkdir(parents=True)
    (api / "tests").mkdir(parents=True)
    (api / "app" / "__init__.py").write_text("")
    (api / "app" / "calc.py").write_text(CALC_SOURCE)
    (api / "tests" / "test_calc.py").write_text(CALC_TEST)
    # Root conftest so pytest prepends the workdir to sys.path and `app` imports.
    (api / "conftest.py").write_text("")
    # The lane's real module -> test-file mapping, stubbed: the contract carries
    # no test-file list, so this is the only thing that tells replay what to run.
    matrix = root / "scripts" / "ci" / "lib" / "mutation_matrix.py"
    matrix.parent.mkdir(parents=True)
    matrix.write_text(MATRIX_STUB)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=root,
        check=True,
    )
    return root


def _calc_record(root: Path, name: str, diff: str, change: str, line: int) -> Path:
    """One shard.verdict.json, exactly as `collect` writes it."""
    path = root / "shard.verdict.json"
    path.write_text(
        json.dumps(
            {
                "modules": [
                    {
                        "module": "app/calc.py",
                        "path": "apps/api/app/calc.py",
                        "status": "survivors",
                        "testfiles": ["tests/test_calc.py"],
                        "survivors": [
                            {
                                "name": name,
                                "function": "total",
                                "file": "app/calc.py",
                                "line": line,
                                "source": "",
                                "change": change,
                                "diff": diff,
                            }
                        ],
                        "excluded": [],
                        "gap_lines": [],
                        "reason": None,
                    }
                ]
            }
        )
    )
    return path


KILLED_DIFF = (
    "--- app/calc.py\n+++ app/calc.py\n@@ -1,2 +1,2 @@\n def total(a, b):\n"
    "-    return a + b\n+    return a - b"
)
SURVIVING_DIFF = (
    "--- app/calc.py\n+++ app/calc.py\n@@ -5,2 +5,2 @@\n def label(name):\n"
    '-    return "total: " + name\n+    return "total: " + None'
)


def _replay(root: Path, source: Path, selector: str) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "replay",
            str(source),
            selector,
            "--repo-root",
            str(root),
            "--api-root",
            str(root / "apps" / "api"),
            "--python",
            sys.executable,
            # pytest-timeout is not in the harness-tooling env this file runs in;
            # the real default is asserted separately, below.
            "--addopts=--strict-markers",
        ]
    )


def test_replay_reports_a_mutant_the_suite_kills(tmp_path: Path) -> None:
    root = _synthetic_repo(tmp_path)
    record = _calc_record(root, "app.calc.x_total__mutmut_1", KILLED_DIFF, "a + b → a - b", 2)
    result = _replay(root, record, "app.calc.x_total__mutmut_1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "KILLED" in result.stdout
    assert "pass without it" in result.stdout


def test_replay_baseline_never_runs_the_mutated_bytecode(tmp_path: Path) -> None:
    """A `+ → -` mutation keeps the file size, and on a fast runner the revert
    lands in the same second — the two things a .pyc header is validated
    against — so an in-tree __pycache__ from the mutated run would make the
    baseline run fail too and report INCONCLUSIVE. Pinning the mtime makes the
    collision certain rather than timing-dependent."""
    root = _synthetic_repo(tmp_path)
    same_second = tmp_path / "python-with-pinned-mtime"
    same_second.write_text(
        f"#!{sys.executable}\n"
        "import os, subprocess, sys\n"
        "os.utime('app/calc.py', (1_700_000_000, 1_700_000_000))\n"
        "sys.exit(subprocess.call([sys.executable, *sys.argv[1:]]))\n"
    )
    same_second.chmod(0o755)
    record = _calc_record(root, "app.calc.x_total__mutmut_1", KILLED_DIFF, "a + b → a - b", 2)

    result = _run(
        [
            "replay",
            str(record),
            "app.calc.x_total__mutmut_1",
            "--repo-root",
            str(root),
            "--api-root",
            str(root / "apps" / "api"),
            "--python",
            str(same_second),
            "--addopts=--strict-markers",
        ]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "KILLED" in result.stdout, result.stdout


def test_replay_reports_a_mutant_the_suite_misses(tmp_path: Path) -> None:
    root = _synthetic_repo(tmp_path)
    record = _calc_record(root, "app.calc.x_label__mutmut_1", SURVIVING_DIFF, "name → None", 6)
    result = _replay(root, record, "app.calc.x_label__mutmut_1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SURVIVED" in result.stdout
    assert "the gap is real" in result.stdout


def test_replay_leaves_the_working_tree_untouched(tmp_path: Path) -> None:
    """The mutation is applied to a scratch copy — never to the checkout."""
    root = _synthetic_repo(tmp_path)
    record = _calc_record(root, "app.calc.x_total__mutmut_1", KILLED_DIFF, "a + b → a - b", 2)
    result = _replay(root, record, "app.calc.x_total__mutmut_1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "apps" / "api" / "app" / "calc.py").read_text() == CALC_SOURCE
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=True
    )
    assert status.stdout.replace("?? shard.verdict.json\n", "") == ""
    assert "working tree unchanged" in result.stdout


def test_replay_selects_by_file_and_line(tmp_path: Path) -> None:
    """`file.py:LINE` replays every mutant recorded on that line."""
    root = _synthetic_repo(tmp_path)
    record = _calc_record(root, "app.calc.x_total__mutmut_1", KILLED_DIFF, "a + b → a - b", 2)
    result = _replay(root, record, "apps/api/app/calc.py:2")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "KILLED" in result.stdout


def test_replay_accepts_a_directory_of_module_records(tmp_path: Path) -> None:
    """The shard's per-module records, before `collect` merges them."""
    root = _synthetic_repo(tmp_path)
    records = root / "shard.records"
    records.mkdir()
    written = _calc_record(root, "app.calc.x_total__mutmut_1", KILLED_DIFF, "a + b → a - b", 2)
    module = json.loads(written.read_text())["modules"][0]
    (records / "app_calc.json").write_text(json.dumps(module))
    written.unlink()
    result = _replay(root, records, "app.calc.x_total__mutmut_1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "KILLED" in result.stdout


def test_replay_reads_a_raw_shard_log(tmp_path: Path) -> None:
    """The artifact you actually have is the log; replay must accept it directly."""
    root = _synthetic_repo(tmp_path)
    log = root / "shard.log"
    log.write_text(
        "=== app/calc.py ===\n"
        "mutating app/calc.py (tests: tests/test_calc.py) ...\n"
        "# app.calc.x_total__mutmut_1: survived\n" + KILLED_DIFF + "\n"
    )
    result = _replay(root, log, "app.calc.x_total__mutmut_1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "KILLED" in result.stdout


def test_replay_fails_loudly_on_an_unknown_selector(tmp_path: Path) -> None:
    root = _synthetic_repo(tmp_path)
    record = _calc_record(root, "app.calc.x_total__mutmut_1", KILLED_DIFF, "a + b → a - b", 2)
    result = _replay(root, record, "app.calc.x_total__mutmut_99")
    assert result.returncode != 0
    assert "nothing in" in result.stderr
    assert "app.calc.x_total__mutmut_1" in result.stderr


def test_replay_fails_loudly_when_the_diff_no_longer_matches(tmp_path: Path) -> None:
    """A verdict from an older run must not silently replay against new code."""
    root = _synthetic_repo(tmp_path)
    record = _calc_record(root, "app.calc.x_total__mutmut_1", KILLED_DIFF, "a + b → a - b", 2)
    (root / "apps" / "api" / "app" / "calc.py").write_text("def total(a, b):\n    return a * b\n")
    result = _replay(root, record, "app.calc.x_total__mutmut_1")
    assert result.returncode != 0
    assert "does not match the file on disk" in result.stderr


def test_mutation_sh_asks_for_the_verdict_directory_instead_of_deriving_it() -> None:
    """`verdict.py dir` is the only thing that knows where verdicts go.

    A copy of the resolution order in shell is wrong the moment it moves, and
    it did move: a `${GAIA_VERDICT_DIR:-<checkout>}` default sent verdicts to
    the checkout, where no runner reads and the gate sees NO VERDICT.
    """
    code = [
        line for line in MUTATION_SH.read_text().splitlines() if not line.lstrip().startswith("#")
    ]
    assert [line for line in code if 'verdict.py" dir' in line or 'verdict.py" dir' in line], (
        "mutation.sh must ask `verdict.py dir` for the verdict directory"
    )
    for derived in ("verify-logs/verdicts", "GAIA_VERDICT_DIR", "RUNNER_TEMP"):
        assert not [line for line in code if derived in line], (
            f"mutation.sh derives the verdict directory itself via {derived}"
        )


def test_default_replay_invocation_stays_local_friendly() -> None:
    """The default pytest args are the ones a 24GB laptop can survive.

    Asserted on the constant because the replay tests above override it: the
    harness-tooling env has no pytest-timeout, and an override that silently
    became the default is how `-n 4` would creep back in.
    """
    source = REPORT.read_text()
    assert 'REPLAY_PYTEST_ARGS = ("-p", "no:xdist")' in source
    assert 'REPLAY_ADDOPTS = "--strict-markers --timeout=120"' in source


def test_mutation_sh_exposes_replay() -> None:
    """The subcommand is reachable and self-documenting from the entrypoint."""
    result = subprocess.run(
        ["bash", str(MUTATION_SH), "replay"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 2
    assert "usage: mutation.sh replay" in result.stderr
    usage = subprocess.run(
        ["bash", str(MUTATION_SH), "nonsense"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert "replay <verdict|dir|shard.log>" in usage.stderr


@pytest.mark.parametrize(
    ("removed", "added", "expected"),
    [
        (["    x = f(a, nx=True)"], ["    x = f(a, nx=None)"], "nx=True → nx=None"),
        (['    f("1", b)'], ["    f(None, b)"], '"1" → None'),
        (["    f(a, b)"], ["    f(b)"], "dropped `a,`"),
        (["    return 1", "    x = 2"], ["    return 1"], "dropped `x = 2`"),
    ],
)
def test_change_summary_names_the_edit(removed: list[str], added: list[str], expected: str) -> None:
    """The one-line change is the whole point: a name plus `→` beats a diff to scan."""
    sys.path.insert(0, str(REPORT.parent))
    import mutation_report

    assert mutation_report.change_summary(removed, added) == expected
