"""regression-proof-verdict: what counts as proof that a bug existed on base.

The verdict reads JUnit, and JUnit records a skip as neither a failure nor an
error — so "not failed and not errored" quietly swept skips in with the passes.
The lane then told the author their fix was not needed and their test did not
exercise the bug it names, about a test that never ran at all. Every contract
test skips without ``USE_REAL_SERVICES=1``, so that is not a corner case.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "verdict", REPO_ROOT / "scripts" / "ci" / "verdict.py"
)
assert _SPEC is not None and _SPEC.loader is not None
verdict = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verdict)


def _junit(tmp_path: Path, name: str, inner: str) -> str:
    path = tmp_path / "junit.xml"
    path.write_text(
        f'<testsuites><testsuite name="pytest"><testcase classname="tests.contracts.test_x" '
        f'file="tests/contracts/test_x.py" line="41" name="{name}">{inner}</testcase>'
        "</testsuite></testsuites>"
    )
    return str(path)


def test_a_skipped_test_is_not_proof(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    junit = _junit(tmp_path, "test_bug", '<skipped message="needs real Mongo"/>')

    assert verdict.cmd_regression_proof_verdict([junit, "--out", str(tmp_path / "v")]) == 1

    out = capsys.readouterr().out
    assert "SKIPPED on base" in out
    assert "PASS on base" not in out


def test_a_failure_on_base_is_proof(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    junit = _junit(tmp_path, "test_bug", '<failure message="assert False"/>')

    assert verdict.cmd_regression_proof_verdict([junit, "--out", str(tmp_path / "v")]) == 0
    assert "fail on base as required" in capsys.readouterr().out


def test_a_pass_on_base_still_fails_the_lane(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    junit = _junit(tmp_path, "test_bug", "")

    assert verdict.cmd_regression_proof_verdict([junit, "--out", str(tmp_path / "v")]) == 1
    assert "PASS on base" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The verdict contract: emit writes all three at once, consolidate reads them.
# ---------------------------------------------------------------------------


def _emit(tmp_path: Path, *args: str) -> int:
    return verdict.cmd_emit(["--out", str(tmp_path / "v"), *args])


def _read(tmp_path: Path, lane: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((tmp_path / "v" / f"{lane}.json").read_text())
    return loaded


def test_emit_writes_the_json_the_annotation_and_the_summary_together(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # All three or none: they were three things a lane could forget separately,
    # and this is the assertion that they now come from one call.
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    _emit(
        tmp_path,
        "--lane",
        "biome",
        "--status",
        "fail",
        "--summary",
        "1 file did not pass",
        "--finding",
        "apps/web/src/a.tsx:12:lint/style/noVar: use const",
        "--advice",
        "pnpm run quality:lint --write",
    )

    doc = _read(tmp_path, "biome")
    assert doc["status"] == "fail"
    assert doc["findings"] == [
        {"file": "apps/web/src/a.tsx", "line": 12, "message": "lint/style/noVar: use const"}
    ]
    assert doc["advice"] == ["pnpm run quality:lint --write"]

    captured = capsys.readouterr()
    assert "::error file=apps/web/src/a.tsx,line=12::lint/style/noVar: use const" in captured.out
    assert "biome: FAIL — 1 file did not pass" in captured.err
    assert "apps/web/src/a.tsx:12" in summary.read_text()


def test_a_finding_message_may_contain_colons(tmp_path: Path) -> None:
    # Splitting on every colon would truncate exactly the messages worth
    # reading — tool codes and assertions are full of them.
    _emit(
        tmp_path,
        "--lane",
        "mypy",
        "--status",
        "fail",
        "--summary",
        "1 error",
        "--finding",
        "app/x.py:9:error: Incompatible return value type (got: int)",
    )
    (found,) = _read(tmp_path, "mypy")["findings"]
    assert found["message"] == "error: Incompatible return value type (got: int)"


def test_a_detail_file_attaches_to_the_finding_it_follows(tmp_path: Path) -> None:
    first, second = tmp_path / "a.txt", tmp_path / "b.txt"
    first.write_text("assert 1 == 2")
    second.write_text("KeyError: 'x'")

    _emit(
        tmp_path,
        "--lane",
        "test-python/unit-a",
        "--status",
        "fail",
        "--summary",
        "2 failed",
        "--finding",
        "t/a.py:1:FAILED test_a",
        "--detail-file",
        str(first),
        "--finding",
        "t/b.py:2:ERROR test_b",
        "--detail-file",
        str(second),
    )

    findings = _read(tmp_path, "test-python/unit-a")["findings"]
    assert [f["detail"] for f in findings] == ["assert 1 == 2", "KeyError: 'x'"]


def test_a_skip_annotates_as_a_warning_not_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A skipped lane is not a red PR. Annotating it `::error` is how a lane
    # that legitimately had nothing to do reads as a failure.
    _emit(
        tmp_path,
        "--lane",
        "python-mypy",
        "--status",
        "skip",
        "--summary",
        "no Python changed",
        "--finding",
        "a.py:1:nothing to do",
    )
    captured = capsys.readouterr()
    assert "::warning file=a.py,line=1::nothing to do" in captured.out
    assert "::error" not in captured.out


def test_emit_reports_but_does_not_decide(tmp_path: Path) -> None:
    # It exits 0 on a failure on purpose: it is called from `if: always()`
    # steps, and the dying belongs at the call site (`ci_verdict_die`).
    assert _emit(tmp_path, "--lane", "x", "--status", "fail", "--summary", "no") == 0


def test_only_if_missing_never_overwrites_a_real_verdict(tmp_path: Path) -> None:
    # The timeout step in the upload-verdict composite runs after the lane; a
    # lane that DID report must keep its own findings.
    _emit(tmp_path, "--lane", "x", "--status", "fail", "--summary", "the real one")
    _emit(
        tmp_path,
        "--lane",
        "x",
        "--status",
        "timed_out",
        "--summary",
        "guessed",
        "--only-if-missing",
    )
    assert _read(tmp_path, "x")["summary"] == "the real one"


def _consolidate(tmp_path: Path, expect: str) -> int:
    return verdict.cmd_consolidate([str(tmp_path / "v"), "--expect", expect])


def test_consolidate_fails_a_lane_that_never_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The enforcement. A lane that stops running looks exactly like a lane with
    # no failures, and this is the only thing that can tell them apart.
    _emit(tmp_path, "--lane", "biome", "--status", "pass", "--summary", "ok")

    assert _consolidate(tmp_path, "biome=success,dead-code=success") == 1
    assert "NO VERDICT" in capsys.readouterr().out


def test_consolidate_lets_a_skipped_lane_report_nothing(tmp_path: Path) -> None:
    # A lane the `changes` job proved untouched runs no steps at all, so it
    # CANNOT write a verdict. Demanding one would red every TS-only PR.
    _emit(tmp_path, "--lane", "biome", "--status", "pass", "--summary", "ok")

    assert _consolidate(tmp_path, "biome=success,python-mypy=skipped") == 0


def test_a_timed_out_lane_is_not_reported_as_a_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The bug this replaces: the gate printed "failure" for a lane that merely
    # ran out of clock, sending readers to hunt a finding nobody had written.
    _emit(tmp_path, "--lane", "test-mutation", "--status", "timed_out", "--summary", "ran out")

    assert _consolidate(tmp_path, "test-mutation=success") == 1
    out = capsys.readouterr().out
    assert "TIMED_OUT" in out
    assert "FAIL" not in out


def test_a_cancelled_lane_with_no_verdict_reads_as_timed_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "v").mkdir()
    assert _consolidate(tmp_path, "semgrep=cancelled") == 1
    assert "timed_out" in capsys.readouterr().out


def test_consolidate_reports_the_worst_status_it_saw(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _emit(tmp_path, "--lane", "a", "--status", "pass", "--summary", "ok")
    _emit(tmp_path, "--lane", "b", "--status", "timed_out", "--summary", "clock")
    _emit(tmp_path, "--lane", "c", "--status", "fail", "--summary", "broken")

    assert _consolidate(tmp_path, "a=success,b=failure,c=failure") == 1
    # fail outranks timed_out: a real finding is what the reader should open
    # first, and a headline of TIMED_OUT would send them to the wrong place.
    assert "quality-gate: FAIL" in capsys.readouterr().out


def test_a_family_of_sub_unit_verdicts_satisfies_one_expected_lane(tmp_path: Path) -> None:
    # How many mutation shards or test-python slices exist is decided at
    # runtime, so the gate expects the family and each sub-unit reports itself.
    _emit(tmp_path, "--lane", "test-mutation/shard-0", "--status", "pass", "--summary", "ok")
    _emit(tmp_path, "--lane", "test-mutation/shard-1", "--status", "pass", "--summary", "ok")

    assert _consolidate(tmp_path, "test-mutation=success") == 0


def test_one_red_sub_unit_reds_the_family(tmp_path: Path) -> None:
    _emit(tmp_path, "--lane", "test-mutation/shard-0", "--status", "pass", "--summary", "ok")
    _emit(tmp_path, "--lane", "test-mutation/shard-1", "--status", "fail", "--summary", "survivor")

    assert _consolidate(tmp_path, "test-mutation=success") == 1


def test_a_verdict_nobody_expected_is_still_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Otherwise a lane could go quiet just by renaming itself, and the mutation
    # gate's per-module verdicts would be dropped from the table.
    _emit(
        tmp_path, "--lane", "mutation/app-services-x", "--status", "fail", "--summary", "survivor"
    )

    assert _consolidate(tmp_path, "biome=skipped") == 1
    assert "mutation/app-services-x" in capsys.readouterr().out


def test_pytest_verdict_points_at_the_failing_test(tmp_path: Path) -> None:
    junit = _junit(
        tmp_path, "test_bug", '<failure message="assert 1 == 2">E  assert 1 == 2</failure>'
    )

    verdict.cmd_pytest_verdict(
        [
            junit,
            "--lane",
            "test-python/unit-a",
            "--path-prefix",
            "apps/api/",
            "--out",
            str(tmp_path / "v"),
        ]
    )

    (found,) = _read(tmp_path, "test-python/unit-a")["findings"]
    assert found["file"] == "apps/api/tests/contracts/test_x.py"
    # JUnit's `line` is 0-based, GitHub annotations are 1-based.
    assert found["line"] == 42
    assert "FAILED" in found["message"]


def test_a_green_pytest_run_that_exited_nonzero_is_not_a_pass(tmp_path: Path) -> None:
    # The flake gate and the coverage threshold both fail the step with every
    # test green; a verdict of `pass` over a red step is worse than none.
    junit = _junit(tmp_path, "test_ok", "")

    verdict.cmd_pytest_verdict(
        [junit, "--lane", "slice", "--exit-code", "1", "--out", str(tmp_path / "v")]
    )

    assert _read(tmp_path, "slice")["status"] == "fail"


def test_a_real_xunit2_report_still_lands_on_the_failing_line(tmp_path: Path) -> None:
    # Verified against a real `pytest --junitxml` run, not invented: pytest's
    # DEFAULT family (xunit2) writes no file/line attributes at all. Reading
    # only the attributes annotated every failure at `<prefix>/` line 1, which
    # renders nowhere — and no hand-written fixture would have shown it.
    junit = tmp_path / "real.xml"
    junit.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">'
        '<testsuite name="pytest" errors="0" failures="1" skipped="0" tests="2">'
        '<testcase classname="tests.unit.test_real" name="test_breaks" time="0.08">'
        '<failure message="assert 0 == 2">def test_breaks():\n'
        "        items = []\n"
        "&gt;       assert len(items) == 2\n"
        "E       assert 0 == 2\n\n"
        "tests/unit/test_real.py:7: AssertionError</failure></testcase>"
        '<testcase classname="tests.unit.test_real" name="test_passes" time="0.001" />'
        "</testsuite></testsuites>"
    )

    verdict.cmd_pytest_verdict(
        [
            str(junit),
            "--lane",
            "slice",
            "--path-prefix",
            "apps/api/",
            "--out",
            str(tmp_path / "v"),
        ]
    )

    (found,) = _read(tmp_path, "slice")["findings"]
    assert (found["file"], found["line"]) == ("apps/api/tests/unit/test_real.py", 7)


def test_only_if_missing_matches_by_lane_id_not_by_file_name(tmp_path: Path) -> None:
    # The mutation gate writes lane `mutation/shard-2` to `mutation/_shard-2.json`,
    # while `verdict_path` would look for `mutation/shard-2.json`. Checking the
    # path alone let the composite's status-derived fallback claim a lane id
    # that already had a real, finding-carrying verdict.
    theirs = tmp_path / "v" / "mutation" / "_shard-2.json"
    theirs.parent.mkdir(parents=True)
    theirs.write_text(
        json.dumps(
            {
                "lane": "mutation/shard-2",
                "status": "fail",
                "summary": "1 survivor",
                "findings": [],
                "advice": [],
            }
        )
    )

    _emit(
        tmp_path,
        "--lane",
        "mutation/shard-2",
        "--status",
        "pass",
        "--summary",
        "passed",
        "--only-if-missing",
    )

    assert not (tmp_path / "v" / "mutation" / "shard-2.json").exists()
    assert _consolidate(tmp_path, "test-mutation@mutation=success") == 1


def test_an_expect_entry_may_name_a_family_other_than_the_job(tmp_path: Path) -> None:
    # The gate's needs entry is `test-mutation`; the lanes it produces are
    # `mutation/<module>`, one per mutated module, and how many there are is
    # only known at runtime.
    _emit(tmp_path, "--lane", "mutation/app-services-budget", "--status", "pass", "--summary", "ok")
    _emit(tmp_path, "--lane", "mutation/app-agents-tools", "--status", "pass", "--summary", "ok")

    assert _consolidate(tmp_path, "test-mutation@mutation=success") == 0


def test_a_family_with_no_members_at_all_is_still_NO_VERDICT(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The enforcement has to survive the aliasing: a mutation job that ran and
    # produced nothing is the case this contract exists for.
    (tmp_path / "v").mkdir()

    assert _consolidate(tmp_path, "test-mutation@mutation=success") == 1
    out = capsys.readouterr().out
    assert "NO VERDICT" in out
    # Reported under the JOB name, which is what the reader sees in the checks
    # list — not under the family, which names no job.
    assert "test-mutation" in out


def test_a_family_that_reported_pass_still_fails_on_its_jobs_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A shard finished its modules and wrote PASS, then the job went red in a
    # LATER step — releasing the test services, stopping the sidecar, the upload
    # itself. `--only-if-missing` stands down on a lane that already reported,
    # so nothing in the verdict tree records that failure and the job result is
    # the only witness left. Trusting the verdicts alone made the required gate
    # green over a job GitHub calls failed.
    _emit(tmp_path, "--lane", "mutation/shard-0", "--status", "pass", "--summary", "clean")

    assert _consolidate(tmp_path, "test-mutation@mutation=failure") == 1
    assert "test-mutation" in capsys.readouterr().out


def test_every_planned_matrix_member_must_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `mutation.sh plan` packs the diff into a known number of shards, and one
    # verdict per shard is the only evidence each of them ran. A shard cancelled
    # before its `if: always()` upload leaves the family satisfied by its
    # siblings: the modules it was carrying go unmutated and nothing says so.
    # The count is of MEMBERS — direct children of the family — not of every
    # verdict under it, because one member reports many sub-unit lanes.
    _emit(tmp_path, "--lane", "mutation/shard-0", "--status", "pass", "--summary", "clean")
    _emit(tmp_path, "--lane", "mutation/app/services/x.py", "--status", "pass", "--summary", "ok")

    assert _consolidate(tmp_path, "test-mutation@mutation*2=success") == 1
    assert "1 of 2" in capsys.readouterr().out
    assert _consolidate(tmp_path, "test-mutation@mutation*1=success") == 0


def test_a_result_only_lane_passes_without_any_verdict(tmp_path: Path) -> None:
    # `select-runner` checks out the default branch and `probe` never checks
    # out, so neither can run the local upload composite. Demanding a verdict
    # from them reds every run; dropping them from the list un-enforces them.
    (tmp_path / "v").mkdir()

    assert _consolidate(tmp_path, "select-runner@result-only=success") == 0


def test_a_result_only_lane_still_reds_the_gate_when_its_job_failed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "v").mkdir()

    assert _consolidate(tmp_path, "select-runner@result-only=failure") == 1
    assert "fail" in capsys.readouterr().out


def test_a_result_only_lane_that_was_cancelled_reads_as_timed_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "v").mkdir()

    assert _consolidate(tmp_path, "probe@result-only=cancelled") == 1
    assert "timed_out" in capsys.readouterr().out


def test_result_only_is_opt_in_never_the_default_for_silence(tmp_path: Path) -> None:
    # The control for the three above: an ordinary lane that reports nothing is
    # still a failure. If `result-only` ever leaked into the default path, this
    # is what would notice.
    (tmp_path / "v").mkdir()

    assert _consolidate(tmp_path, "biome=success") == 1


# ---------------------------------------------------------------------------
# --job-status: the caller's job.status decides a silent lane's verdict.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("job_status", "expected"),
    [("success", "pass"), ("failure", "fail"), ("cancelled", "timed_out"), ("skipped", "skip")],
)
def test_the_job_status_decides_a_silent_lanes_verdict(
    tmp_path: Path, job_status: str, expected: str
) -> None:
    # This mapping used to be three `if: success()/failure()/cancelled()` steps
    # inside the composite. Inside a composite those functions evaluate the
    # ACTION's own prior steps, not the job, so the success branch always won:
    # run 34584038269's mutation shard 5/6 died in `setup-python-test-env` and
    # still uploaded {"lane": "mutation/shard-4", "status": "pass"}. The caller
    # now passes ${{ job.status }} and the mapping lives here, where this test
    # can reach it.
    _emit(tmp_path, "--lane", "lane", "--job-status", job_status)

    assert _read(tmp_path, "lane")["status"] == expected


def test_a_failing_job_status_carries_advice_worth_reading(tmp_path: Path) -> None:
    _emit(tmp_path, "--lane", "lane", "--job-status", "failure")

    doc = _read(tmp_path, "lane")
    assert "only in this job's log" in doc["summary"]
    assert doc["advice"], "a failed lane with no findings must at least say where to look"


def test_a_job_status_never_overwrites_the_lanes_own_verdict(tmp_path: Path) -> None:
    # The composite always runs; a lane that reported real findings keeps them
    # even when the job as a whole is green.
    _emit(
        tmp_path,
        "--lane",
        "lane",
        "--status",
        "fail",
        "--summary",
        "2 survivors",
        "--finding",
        "app/x.py:3:survivor",
    )

    _emit(tmp_path, "--lane", "lane", "--job-status", "success", "--only-if-missing")

    doc = _read(tmp_path, "lane")
    assert doc["status"] == "fail"
    assert doc["findings"]


def test_emit_refuses_both_a_status_and_a_job_status(tmp_path: Path) -> None:
    # They answer the same question two ways; silently preferring one is how a
    # caller ends up asserting something it did not mean.
    with pytest.raises(SystemExit):
        _emit(
            tmp_path, "--lane", "l", "--status", "pass", "--summary", "s", "--job-status", "failure"
        )
    with pytest.raises(SystemExit):
        _emit(tmp_path, "--lane", "l", "--summary", "s")


# ---------------------------------------------------------------------------
# Where verdicts live, and who owns them.
# ---------------------------------------------------------------------------


def test_the_env_var_decides_the_verdict_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(verdict.VERDICT_DIR_ENV, str(tmp_path / "elsewhere"))

    verdict.cmd_emit(["--lane", "biome", "--job-status", "success"])

    assert (tmp_path / "elsewhere" / "biome.json").exists()


def test_a_runner_writes_to_its_own_per_job_temp_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Not the checkout. A self-hosted workspace persists between jobs, so a
    # verdict left in the tree is uploaded by the NEXT job on that runner —
    # stale lanes from another run reaching a gate. RUNNER_TEMP is wiped.
    monkeypatch.delenv(verdict.VERDICT_DIR_ENV, raising=False)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "runner-temp"))

    assert verdict.default_out_dir() == tmp_path / "runner-temp" / "verdicts"


def test_a_dev_machine_still_writes_into_the_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    # The control: local runs are unchanged, so `verify-logs/verdicts` stays
    # the place to look after `mise ci:local`.
    monkeypatch.delenv(verdict.VERDICT_DIR_ENV, raising=False)
    monkeypatch.delenv("RUNNER_TEMP", raising=False)

    assert verdict.default_out_dir() == verdict.CHECKOUT_VERDICT_DIR


def test_a_verdict_this_job_does_not_own_is_rejected_by_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The real one: run 34586506166's gate table carried
    # `mutation/app/does_not_exist.py`, a fixture path written by an end-to-end
    # TEST that `test-harness-tools` ran, uploaded as that lane's verdict.
    _emit(tmp_path, "--lane", "test-harness-tools", "--job-status", "success")
    _emit(
        tmp_path, "--lane", "mutation/app/does_not_exist.py", "--status", "error", "--summary", "x"
    )

    code = verdict.cmd_check_ownership(
        ["--family", "test-harness-tools", "--out", str(tmp_path / "v")]
    )

    assert code == 1
    out = capsys.readouterr().out
    assert "does_not_exist.py" in out
    assert "::error file=" in out, "a stray file must point at itself, not at a phantom lane"


def test_a_family_owns_every_lane_beneath_it(tmp_path: Path) -> None:
    # The mutation shards pass `family: mutation` because mutation.sh writes one
    # verdict per module there rather than under the shard's own lane.
    _emit(tmp_path, "--lane", "mutation/shard-4", "--job-status", "success")
    _emit(tmp_path, "--lane", "mutation/app-services-budget", "--status", "fail", "--summary", "x")

    assert verdict.cmd_check_ownership(["--family", "mutation", "--out", str(tmp_path / "v")]) == 0


def test_ownership_is_not_a_substring_match(tmp_path: Path) -> None:
    # `mutation-fixtures` is not under `mutation`; a prefix test without the
    # separator would quietly adopt it.
    _emit(tmp_path, "--lane", "mutation-fixtures", "--status", "error", "--summary", "x")

    assert verdict.cmd_check_ownership(["--family", "mutation", "--out", str(tmp_path / "v")]) == 1


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({"GAIA_VERDICT_DIR": "/explicit/dir", "RUNNER_TEMP": "/runner/tmp"}, "/explicit/dir"),
        ({"RUNNER_TEMP": "/runner/tmp"}, "/runner/tmp/verdicts"),
        ({}, None),
    ],
    ids=["env-var-wins", "runner-temp", "checkout-fallback"],
)
def test_dir_prints_the_directory_emit_would_write_to(
    environment: dict[str, str],
    expected: str | None,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `mutation.sh` reads this instead of re-deriving it. The bash version had
    # no RUNNER_TEMP rung, so on a runner it named the CHECKOUT while the
    # composite uploaded from the runner's temp dir — every verdict written
    # through it would have missed the gate silently.
    for key in (verdict.VERDICT_DIR_ENV, "RUNNER_TEMP"):
        monkeypatch.delenv(key, raising=False)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)

    assert verdict.cmd_dir([]) == 0

    printed = capsys.readouterr().out
    assert printed == f"{expected or verdict.CHECKOUT_VERDICT_DIR}\n", (
        "one line, no trailing noise — a script reads this into a variable"
    )


def test_ci_verdict_still_finds_verdict_py_after_the_caller_changes_directory(
    tmp_path: Path,
) -> None:
    """`ci_verdict` is called from inside worktrees and scratch dirs.

    regression-proof sources log.sh as `../../scripts/ci/pytest.sh` does —
    through a relative path — and then `cd`s into the base worktree before it
    emits. Building the verdict.py path from ${BASH_SOURCE[0]} at CALL time
    resolved it against that new directory, and the lane died with "can't open
    …/../../scripts/ci/lib/../verdict.py" on run 34586500580 (#1202). The path
    has to be fixed at source time.
    """
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    script = (
        # Source through a RELATIVE path from apps/api, exactly like the lane.
        'cd "$REPO/apps/api" && source ../../scripts/ci/lib/log.sh && '
        f'cd "{elsewhere}" && '
        f'ci_verdict --lane probe --status pass --summary ok --out "{tmp_path}/verdicts"'
    )
    result = subprocess.run(
        ["bash", "-c", script],
        env={**os.environ, "REPO": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "verdicts" / "probe.json").exists()


# --- mirror-previous-gate ---------------------------------------------------
#
# The gate cannot skip on a PR edit — a skipped required check counts as
# PASSING, so skipping would overwrite a RED verdict on that head SHA with a
# green tick. It cannot re-run the lanes either: nothing changed. So it repeats
# what the same head SHA already concluded, read back from the API.

MIRROR_REPO = "theexperiencecompany/gaia"
MIRROR_SHA = "c9d667254c9d667254c9d667254c9d667254c9d6"
MIRROR_JOB = "quality-gate"
CURRENT_RUN = 999


def _gate_job(conclusion: str | None, *, status: str = "completed") -> dict[str, Any]:
    return {"name": MIRROR_JOB, "status": status, "conclusion": conclusion}


def _jobs_with_lane(gate: dict[str, Any], lane: str | None) -> list[dict[str, Any]]:
    """Build a run's job listing: one lane beside the gate job."""
    return [{"name": "build", "conclusion": lane}, gate]


def _stub_api(
    monkeypatch: pytest.MonkeyPatch,
    runs: list[dict[str, Any]],
    jobs: dict[int, list[dict[str, Any]]],
) -> list[str]:
    """Stub `gh api` with one runs listing and one job listing per run."""
    asked: list[str] = []

    def fake(endpoint: str) -> dict[str, Any] | None:
        asked.append(endpoint)
        if "/jobs" in endpoint:
            run_id = int(endpoint.split("/runs/")[1].split("/jobs")[0])
            return {"jobs": jobs.get(run_id, [])}
        return {"workflow_runs": runs}

    monkeypatch.setattr(verdict, "_gh_json", fake)
    return asked


def _mirror() -> int:
    return verdict.cmd_mirror_previous_gate(
        [
            "--repo",
            MIRROR_REPO,
            "--sha",
            MIRROR_SHA,
            "--workflow",
            "main.yml",
            "--job",
            MIRROR_JOB,
            "--run-id",
            str(CURRENT_RUN),
        ]
    )


def test_a_previous_success_on_this_sha_mirrors_as_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    asked = _stub_api(
        monkeypatch,
        [{"id": 7, "status": "completed"}],
        {7: [_gate_job("success")]},
    )

    assert _mirror() == 0
    assert "success" in capsys.readouterr().out
    # The HEAD sha, not the merge commit: that is what the check runs and branch
    # protection are attached to.
    assert f"head_sha={MIRROR_SHA}" in asked[0], asked


def test_a_previous_failure_on_this_sha_reds_the_gate_again(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The whole point: a title edit after a RED run must not hand the same head
    # SHA a green required check.
    _stub_api(monkeypatch, [{"id": 7, "status": "completed"}], {7: [_gate_job("failure")]})

    assert _mirror() == 1
    assert "::error::" in capsys.readouterr().out


def test_a_cancelled_previous_gate_is_not_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_api(monkeypatch, [{"id": 7, "status": "completed"}], {7: [_gate_job("cancelled")]})

    assert _mirror() == 1


def test_no_completed_run_on_this_sha_fails_rather_than_assuming(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # An edit landing while the only run is still in flight has nothing to
    # mirror. Failing is recoverable (re-run the gate); a green tick is not.
    _stub_api(monkeypatch, [{"id": 8, "status": "in_progress"}], {})

    assert _mirror() == 1
    assert "latest validation has not concluded" in capsys.readouterr().out


def test_the_run_doing_the_mirroring_is_not_its_own_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This run is itself listed under the same head SHA; reading its own
    # in-flight gate job would be circular.
    _stub_api(
        monkeypatch,
        [{"id": CURRENT_RUN, "status": "completed"}],
        {CURRENT_RUN: [_gate_job("success")]},
    )

    assert _mirror() == 1


def test_a_run_whose_gate_never_concluded_is_not_a_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A gate job skipped rather than concluded (every run before this
    # subcommand, on a plain edit) carries no verdict, and a skip must never
    # read as a pass.
    _stub_api(
        monkeypatch,
        [{"id": 9, "status": "completed"}],
        {9: [_gate_job("skipped")]},
    )

    assert _mirror() == 1


def test_a_plain_edit_run_is_not_the_validation_it_mirrored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An earlier edit's run skipped every lane and only republished run 7's
    # verdict, so it is not evidence of its own — the failure underneath it is.
    _stub_api(
        monkeypatch,
        [{"id": 9, "status": "completed"}, {"id": 7, "status": "completed"}],
        {
            9: _jobs_with_lane(_gate_job("success"), "skipped"),
            7: _jobs_with_lane(_gate_job("failure"), "failure"),
        },
    )

    assert _mirror() == 1


def test_a_newer_validation_still_running_blocks_an_older_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A retarget re-scoped every lane against the new base and has not decided
    # yet; mirroring the success it supersedes would publish a stale pass.
    _stub_api(
        monkeypatch,
        [{"id": 9, "status": "in_progress"}, {"id": 7, "status": "completed"}],
        {
            9: _jobs_with_lane(_gate_job(None, status="queued"), None),
            7: _jobs_with_lane(_gate_job("success"), "success"),
        },
    )

    assert _mirror() == 1
    assert "latest validation has not concluded" in capsys.readouterr().out


def test_a_newer_cancelled_validation_blocks_an_older_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A cancelled run's gate job never starts, so it concludes `skipped` — the
    # one value that must not let the search fall back to an older success.
    _stub_api(
        monkeypatch,
        [{"id": 9, "status": "completed"}, {"id": 7, "status": "completed"}],
        {
            9: _jobs_with_lane(_gate_job("skipped"), "cancelled"),
            7: _jobs_with_lane(_gate_job("success"), "success"),
        },
    )

    assert _mirror() == 1


def test_the_newest_substantive_run_decides_the_mirror(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The newest run passed after the older one failed, so the mirror is green.
    _stub_api(
        monkeypatch,
        [{"id": 9, "status": "completed"}, {"id": 7, "status": "completed"}],
        {
            9: _jobs_with_lane(_gate_job("success"), "success"),
            7: _jobs_with_lane(_gate_job("failure"), "failure"),
        },
    )

    assert _mirror() == 0
    assert "mirroring run 9" in capsys.readouterr().out


def test_an_unreachable_api_is_a_failure_not_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verdict, "_gh_json", lambda endpoint: None)

    assert _mirror() == 1


class _FakeClock:
    """Stands in for verdict's `time`: sleeping advances the clock instead of waiting."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps = 0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.now += seconds


def _mirror_waiting(seconds: int) -> int:
    return verdict.cmd_mirror_previous_gate(
        [
            "--repo",
            MIRROR_REPO,
            "--sha",
            MIRROR_SHA,
            "--workflow",
            "main.yml",
            "--job",
            MIRROR_JOB,
            "--run-id",
            str(CURRENT_RUN),
            "--wait-seconds",
            str(seconds),
        ]
    )


def test_an_edit_waits_for_the_run_it_no_longer_cancels(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # An edit used to cancel the real run on the same merge sha. It now runs in
    # its own concurrency group, so the real run finishes and the edit's gate
    # repeats that verdict instead of failing while it is still in flight.
    clock = _FakeClock()
    monkeypatch.setattr(verdict, "time", clock)
    still_running = {"id": 8, "status": "in_progress"}
    finished = {"id": 8, "status": "completed"}
    polls: list[str] = []

    def fake(endpoint: str) -> dict[str, Any] | None:
        polls.append(endpoint)
        done = clock.sleeps >= 2
        if "/jobs" in endpoint:
            return {"jobs": _jobs_with_lane(_gate_job("success" if done else None), "success")}
        return {"workflow_runs": [finished if done else still_running]}

    monkeypatch.setattr(verdict, "_gh_json", fake)

    assert _mirror_waiting(600) == 0
    assert clock.sleeps == 2
    assert "mirroring run 8" in capsys.readouterr().out


def test_a_wait_that_runs_out_fails_rather_than_assuming(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = _FakeClock()
    monkeypatch.setattr(verdict, "time", clock)
    _stub_api(
        monkeypatch,
        [{"id": 8, "status": "in_progress"}],
        {8: _jobs_with_lane(_gate_job(None, status="in_progress"), None)},
    )

    assert _mirror_waiting(90) == 1
    assert clock.now >= 90
    assert "latest validation has not concluded" in capsys.readouterr().out


def test_a_finished_run_whose_gate_never_ran_is_not_waited_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A cancelled run is completed with a skipped gate: it will never conclude,
    # so waiting on it would only burn the timeout before the same failure.
    clock = _FakeClock()
    monkeypatch.setattr(verdict, "time", clock)
    _stub_api(
        monkeypatch,
        [{"id": 9, "status": "completed"}],
        {9: _jobs_with_lane(_gate_job("skipped"), "cancelled")},
    )

    assert _mirror_waiting(600) == 1
    assert clock.sleeps == 0


# --- reuse-plan --------------------------------------------------------------
#
# A push re-ran every lane its PR touched against the base, even when the push
# changed nothing a lane reads. reuse-plan carries a lane's last PASS forward
# when nothing in its scope and nothing in CI tooling changed since — and must
# never carry forward a failure, a pass on another base, or a pass it cannot
# diff against.

REUSE_WORKFLOW = """\
jobs:
  changes:
    name: Detect changed languages
  biome:
    name: Biome lint + format
  python-static:
    name: Python static
"""
REUSE_LANES = {
    "lanes": [
        {"name": "biome", "ci_job": "biome", "scope": r"\.(ts|tsx)$"},
        {"name": "python-ruff", "ci_job": "python-static", "scope": r"\.py$"},
        {"name": "py-tests", "scope": r"\.py$"},
    ]
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, path: str, body: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", path)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def reuse_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "code-quality.yml").write_text(REUSE_WORKFLOW)
    (repo / "lanes.json").write_text(json.dumps(REUSE_LANES))
    _commit(repo, "apps/web/a.ts", "one")
    monkeypatch.setattr(verdict, "REPO_ROOT", repo)
    return repo


def _stub_runs(
    monkeypatch: pytest.MonkeyPatch, runs: list[tuple[int, str, str, dict[str, str]]]
) -> None:
    """Stub the PR's runs, newest first, each (id, head sha, base ref, {job name: conclusion})."""
    listing = {
        "workflow_runs": [
            {
                "id": run_id,
                "status": "completed",
                "head_sha": sha,
                "pull_requests": [{"base": {"ref": base}}],
            }
            for run_id, sha, base, _ in runs
        ]
    }
    jobs = {
        run_id: [{"name": name, "conclusion": result} for name, result in results.items()]
        for run_id, _, _, results in runs
    }

    def fake(endpoint: str) -> dict[str, Any] | None:
        if "/jobs" in endpoint:
            return {"jobs": jobs[int(endpoint.split("/runs/")[1].split("/jobs")[0])]}
        return listing

    monkeypatch.setattr(verdict, "_gh_json", fake)


def _plan(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, head: str, *extra: str
) -> dict[str, str]:
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert (
        verdict.cmd_reuse_plan(
            [
                "--repo",
                MIRROR_REPO,
                "--workflow",
                "code-quality.yml",
                "--branch",
                "feature",
                "--base",
                "master",
                "--head-sha",
                head,
                "--run-id",
                str(CURRENT_RUN),
                "--event",
                "pull_request",
                "--lanes",
                str(repo / "lanes.json"),
                *extra,
            ]
        )
        == 0
    )
    fields = dict(line.split("=", 1) for line in out.read_text().splitlines())
    return json.loads(fields["reused"])


PASSED = {"Biome lint + format": "success", "Python static": "success"}


def test_a_lane_whose_scope_did_not_change_since_its_pass_is_reused(
    reuse_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    anchor = _git(reuse_repo, "rev-parse", "HEAD")
    head = _commit(reuse_repo, "apps/api/x.py", "py only")
    _stub_runs(monkeypatch, [(7, anchor, "master", PASSED)])

    reused = _plan(reuse_repo, monkeypatch, tmp_path, head)

    # The TS lane read nothing that changed; the Python lane did.
    assert list(reused) == ["biome"]
    assert "run 7" in reused["biome"]


def test_a_ci_or_tooling_change_reuses_nothing(
    reuse_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    anchor = _git(reuse_repo, "rev-parse", "HEAD")
    head = _commit(reuse_repo, ".github/workflows/code-quality.yml", REUSE_WORKFLOW + "# edit\n")
    _stub_runs(monkeypatch, [(7, anchor, "master", PASSED)])

    assert _plan(reuse_repo, monkeypatch, tmp_path, head) == {}


def test_a_failed_lane_is_never_carried_forward(
    reuse_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    anchor = _git(reuse_repo, "rev-parse", "HEAD")
    head = _commit(reuse_repo, "docs/notes.md", "unrelated")
    _stub_runs(
        monkeypatch,
        [(7, anchor, "master", {"Biome lint + format": "failure", "Python static": "skipped"})],
    )

    # Neither a failure nor a skip is a pass to reuse, however little changed.
    assert _plan(reuse_repo, monkeypatch, tmp_path, head) == {}


def test_the_anchor_is_the_newest_pass_not_the_newest_run(
    reuse_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    passed_at = _git(reuse_repo, "rev-parse", "HEAD")
    failed_at = _commit(reuse_repo, "apps/web/b.ts", "broke biome")
    head = _commit(reuse_repo, "apps/web/b.ts", "fixed biome")
    _stub_runs(
        monkeypatch,
        [
            (
                8,
                failed_at,
                "master",
                {"Biome lint + format": "failure", "Python static": "success"},
            ),
            (7, passed_at, "master", PASSED),
        ],
    )

    reused = _plan(reuse_repo, monkeypatch, tmp_path, head)

    # Biome's last pass predates two TS edits, so it runs; Python static passed
    # at run 8 and nothing Python changed after it.
    assert list(reused) == ["python-static"]
    assert "run 8" in reused["python-static"]


def test_a_pass_against_another_base_is_not_reused(
    reuse_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    anchor = _git(reuse_repo, "rev-parse", "HEAD")
    head = _commit(reuse_repo, "docs/notes.md", "unrelated")
    _stub_runs(monkeypatch, [(7, anchor, "feature/parent", PASSED)])

    # A retarget changes what every lane diffs against, with no file changing.
    assert _plan(reuse_repo, monkeypatch, tmp_path, head) == {}


def test_an_anchor_missing_from_the_checkout_reuses_nothing(
    reuse_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    head = _commit(reuse_repo, "docs/notes.md", "unrelated")
    _stub_runs(monkeypatch, [(7, "0" * 40, "master", PASSED)])

    # A force-push orphans the old head; without a diff there is no proof.
    assert _plan(reuse_repo, monkeypatch, tmp_path, head) == {}


def test_a_manual_rerun_reuses_nothing(
    reuse_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    anchor = _git(reuse_repo, "rev-parse", "HEAD")
    head = _commit(reuse_repo, "docs/notes.md", "unrelated")
    _stub_runs(monkeypatch, [(7, anchor, "master", PASSED)])

    assert _plan(reuse_repo, monkeypatch, tmp_path, head, "--run-attempt", "2") == {}


def test_an_unreadable_api_reuses_nothing(
    reuse_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    head = _commit(reuse_repo, "docs/notes.md", "unrelated")
    monkeypatch.setattr(verdict, "_gh_json", lambda endpoint: None)

    assert _plan(reuse_repo, monkeypatch, tmp_path, head) == {}


def test_display_names_match_the_real_workflow() -> None:
    yaml = pytest.importorskip("yaml")
    workflow = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "code-quality.yml"
    expected = {
        job: spec.get("name", job)
        for job, spec in yaml.safe_load(workflow.read_text())["jobs"].items()
    }

    names = verdict._job_display_names(workflow)

    lanes = json.loads((workflow.parents[2] / "scripts" / "dev" / "verify-lanes.json").read_text())
    for job in {lane["ci_job"] for lane in lanes["lanes"] if lane.get("ci_job")}:
        assert names[job] == expected[job], job


def test_consolidate_labels_a_reused_lane(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        verdict.cmd_consolidate(
            [
                str(tmp_path),
                "--expect",
                "biome=skipped",
                "--reused",
                json.dumps({"biome": "passed at abc in run 7"}),
            ]
        )
        == 0
    )
    assert "reused — passed at abc in run 7" in capsys.readouterr().out
