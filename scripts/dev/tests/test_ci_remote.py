"""`mise ci:remote` — the failure itself, not a link to it (scripts/dev/ci_remote.py).

What this covers is the gap between "the PR is red" and "here is what broke".
The old output printed `FAIL <name> <url>`; following that URL led to
`gh run view --log`, which refuses until the whole run completes, so the working
path was downloading the job's artifact and grepping a 190k-line log — ~12
commands per red lane.

Every assertion here is about that gap closing:
  - a lane's verdict artifact is read (artifacts are downloadable mid-run) and
    rendered as `file:line — message`, with long detail folded behind
    `--verbose`;
  - when a lane uploaded no verdict, the job log is cleaned (ANSI, the per-line
    timestamp prefix, grouping markers) and windowed on the *last* `##[error]`
    rather than the literal end of the file — the fixture is a trimmed excerpt
    of a genuine shard log (PR #1161, run 34530501840, mutation-log-2) where the
    error sits 51 lines from the end, so a plain tail shows `git config` calls;
  - a stack PR whose GitHub base disagrees with its stack parent is called out,
    because that mismatch scoped a gate to 119 modules instead of 11;
  - `--json` carries the same four things so an agent can parse them.

The network seam is mocked at `gh` / `gh_bytes` — the two functions that shell
out. Everything above them is the real code.

Run: uv run pytest scripts/dev/tests/test_ci_remote.py -p no:xdist
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys
from typing import Any
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ci_remote  # the path insert above must precede this import

# A trimmed excerpt of the real job log for `Mutation shard 3/6` — the bytes
# `gh api .../jobs/103050508136/logs` returns, ISO prefixes and all. The last
# `##[error]` is followed by post-job cleanup, which is the whole point.
REAL_JOB_LOG = (
    "2026-09-10T21:39:26.6261000Z tests/unit/workers/test_worker_lifecycle.py::test_max_jobs PASSED [ 67%]\n"
    "2026-09-10T21:39:26.6261100Z tests/unit/workers/test_worker_lifecycle.py::test_log_results FAILED [ 68%]\n"
    "2026-09-10T21:39:26.6261409Z ===================== 76 passed in 6.58s =====================\n"
    "2026-09-10T21:39:26.6261514Z     exit code 0\n"
    "2026-09-10T21:39:26.6261522Z \n"
    "2026-09-10T21:39:26.6263167Z SKIP: app/workers/config/worker_settings.py — no covering tests\n"
    "2026-09-10T21:39:26.6263384Z       mutmut 3.7 cannot mutate decorated functions (FastAPI\n"
    "2026-09-10T21:39:26.6267265Z ##[error]mutation failed for: app/api/v1/endpoints/bot.py\n"
    "2026-09-10T21:39:26.6270852Z ##[error]Process completed with exit code 1.\n"
    "2026-09-10T21:39:26.6404318Z ##[group]Run actions/upload-artifact@043fb46\n"
    "2026-09-10T21:39:26.6405100Z   compression-level: 6\n"
    "2026-09-10T21:39:26.6405943Z ##[endgroup]\n"
    "2026-09-10T21:39:27.8128627Z \x1b[36mUploading artifact: mutation-log-2.zip\x1b[0m\n"
    "2026-09-10T21:39:33.6318578Z [command]/usr/bin/git config --global --add safe.directory /x\n"
    "2026-09-10T21:39:33.9560775Z Cleaning up orphan processes\n"
)

VERDICT: dict[str, Any] = {
    "lane": "mutation-shard-3",
    "status": "fail",
    "summary": "2 modules have surviving mutants",
    "findings": [
        {
            "file": "app/api/v1/endpoints/bot.py",
            "line": 212,
            "message": "survivor: the once-a-day claim always succeeds",
            "detail": "line 1\nline 2\nline 3\nline 4\nline 5",
        },
        {"file": "app/services/payments/payment_webhook_service.py", "message": "survivor: no-op"},
    ],
    "advice": ["Reproduce with `mise mutation:replay app/api/v1/endpoints/bot.py`."],
}

PR_META: dict[str, Any] = {
    "number": 7,
    "title": "feat: a thing",
    "url": "https://github.com/o/r/pull/7",
    "headRefOid": "abc123",
    "baseRefName": "master",
    "headRefName": "feat/thing",
    "isDraft": False,
    "mergeable": "MERGEABLE",
    "reviewDecision": None,
    "reviewThreads": {"totalCount": 1, "nodes": [{"isResolved": True}]},
}

FAILED_CHECK: dict[str, Any] = {
    "name": "Mutation shard 3/6 (19 modules)",
    "status": "completed",
    "conclusion": "failure",
    "html_url": "https://github.com/o/r/actions/runs/99/job/1234",
    "app": {"slug": "github-actions"},
}
PASSED_CHECK: dict[str, Any] = {
    "name": "lint",
    "status": "completed",
    "conclusion": "success",
    "html_url": "https://github.com/o/r/actions/runs/99/job/1235",
    "app": {"slug": "github-actions"},
}


def verdict_zip(*verdicts: dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for i, verdict in enumerate(verdicts):
            archive.writestr(f"verify-logs/verdicts/{i}.json", json.dumps(verdict))
    return buffer.getvalue()


class FakeGh:
    """Routes `gh` argv to canned payloads and records what was asked for."""

    def __init__(
        self,
        *,
        checks: list[dict[str, Any]],
        pr_meta: dict[str, Any] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        zip_blob: bytes = b"",
        zip_blobs: dict[int, bytes] | None = None,
        job_log: str = REAL_JOB_LOG,
    ) -> None:
        self.checks = checks
        self.pr_meta = pr_meta or PR_META
        self.artifacts = artifacts if artifacts is not None else []
        self.zip_blob = zip_blob
        self.zip_blobs = zip_blobs or {}
        self.job_log = job_log
        self.calls: list[str] = []

    def text(
        self, args: list[str], timeout_s: int, stdin_text: str | None = None
    ) -> tuple[int, str, str]:
        endpoint = args[1] if len(args) > 1 else ""
        self.calls.append(endpoint)
        if endpoint == "graphql":
            return 0, json.dumps({"data": {"repository": {"pullRequest": self.pr_meta}}}), ""
        if "/check-runs" in endpoint:
            return 0, json.dumps({"check_runs": self.checks}), ""
        if "/artifacts" in endpoint:
            return 0, json.dumps({"artifacts": self.artifacts}), ""
        raise AssertionError(f"unexpected gh call: {args}")

    def binary(self, args: list[str], timeout_s: int) -> tuple[int, bytes, str]:
        endpoint = args[-1]
        self.calls.append(endpoint)
        if endpoint.endswith("/zip"):
            artifact_id = int(endpoint.rsplit("/", 2)[-2])
            return 0, self.zip_blobs.get(artifact_id, self.zip_blob), ""
        if endpoint.endswith("/logs"):
            return 0, self.job_log.encode(), ""
        raise AssertionError(f"unexpected gh_bytes call: {args}")


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch):
    """Install a FakeGh and stub the git / gh-stack lookups around it."""

    def install(fake: FakeGh, stack: dict[str, Any] | None = None) -> FakeGh:
        monkeypatch.setattr(ci_remote, "gh", fake.text)
        monkeypatch.setattr(ci_remote, "gh_bytes", fake.binary)
        monkeypatch.setattr(ci_remote, "parse_repo", lambda: ("o", "r"))
        monkeypatch.setattr(ci_remote, "current_branch", lambda: "feat/thing")
        monkeypatch.setattr(
            ci_remote,
            "resolve_pr",
            lambda *_a, **_k: (7, "https://github.com/o/r/pull/7", "abc123"),
        )
        monkeypatch.setattr(ci_remote, "fetch_stack", lambda _repo: stack)
        # Off the box by default: the real call shells out to runner.sh, and a
        # suite whose output depends on the host's load average is not a test.
        monkeypatch.setattr(ci_remote, "runner_health", lambda: None)
        return fake

    return install


def run_cli(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["ci_remote.py", *argv])
    return ci_remote.main()


# --------------------------------------------------------------------- log tail cleaning


def test_the_tail_is_cleaned_of_everything_that_makes_a_raw_log_unreadable() -> None:
    lines = ci_remote.clean_log(REAL_JOB_LOG)
    joined = "\n".join(lines)
    assert "2026-09-10T21:39" not in joined, "per-line ISO timestamp prefix survived"
    assert "\x1b[" not in joined, "ANSI escapes survived"
    assert "##[group]" not in joined and "##[endgroup]" not in joined
    assert "" not in lines, "blank lines survived"
    assert "ERROR: Process completed with exit code 1." in lines
    # A -vv shard prints hundreds of PASSED lines; they would fill the window.
    assert not any("PASSED [" in line for line in lines)
    assert any("test_log_results FAILED [ 68%]" in line for line in lines)


def test_the_run_view_prefix_form_is_stripped_too() -> None:
    raw = "shard 3\tRun mutation\t2026-09-10T21:39:26.6267265Z ##[error]mutation failed for: x.py"
    assert ci_remote.clean_log(raw) == ["ERROR: mutation failed for: x.py"]


def test_the_tail_ends_at_the_failure_not_at_the_end_of_the_log() -> None:
    """A shard log's literal tail is artifact uploads and `git config` calls."""
    tail = ci_remote.failure_tail(ci_remote.clean_log(REAL_JOB_LOG), limit=5)
    assert tail[-1] == "ERROR: Process completed with exit code 1."
    assert "mutation failed for: app/api/v1/endpoints/bot.py" in tail[-2]
    assert not any("Cleaning up orphan processes" in line for line in tail)
    assert not any("git config" in line for line in tail)
    assert len(tail) == 5


def test_a_log_with_no_error_marker_falls_back_to_the_literal_tail() -> None:
    lines = [f"line {i}" for i in range(10)]
    assert ci_remote.failure_tail(lines, limit=3) == ["line 7", "line 8", "line 9"]


# ------------------------------------------------------------------------ verdict output


def test_a_failing_verdict_prints_lane_summary_and_file_line_message(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire(
        FakeGh(
            checks=[FAILED_CHECK, PASSED_CHECK],
            artifacts=[{"id": 55, "name": "verdict-mutation-shard-3", "expired": False}],
            zip_blob=verdict_zip(VERDICT),
        )
    )
    assert run_cli(monkeypatch, []) == 1
    out = capsys.readouterr().out
    assert "FAIL  Mutation shard 3/6 (19 modules)  [failed]" in out
    assert "  mutation-shard-3  [fail]" in out
    assert "2 modules have surviving mutants" in out
    assert "app/api/v1/endpoints/bot.py:212 — survivor: the once-a-day claim always succeeds" in out
    # A finding with no line number still renders, without a dangling colon.
    assert "app/services/payments/payment_webhook_service.py — survivor: no-op" in out


def test_long_detail_is_folded_to_three_lines_until_verbose(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args: dict[str, Any] = {
        "checks": [FAILED_CHECK],
        "artifacts": [{"id": 55, "name": "verdict-mutation-shard-3", "expired": False}],
        "zip_blob": verdict_zip(VERDICT),
    }
    wire(FakeGh(**args))
    run_cli(monkeypatch, [])
    folded = capsys.readouterr().out
    assert "line 3" in folded and "line 4" not in folded
    assert "… 2 more lines (--verbose)" in folded

    wire(FakeGh(**args))
    run_cli(monkeypatch, ["--verbose"])
    full = capsys.readouterr().out
    assert "line 5" in full
    assert "more lines (--verbose)" not in full


def test_the_verdict_is_preferred_and_the_job_log_is_not_fetched(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = wire(
        FakeGh(
            checks=[FAILED_CHECK],
            artifacts=[{"id": 55, "name": "verdict-mutation-shard-3", "expired": False}],
            zip_blob=verdict_zip(VERDICT),
        )
    )
    run_cli(monkeypatch, ["--verbose"])
    assert not any(c.endswith("/logs") for c in fake.calls), "job log fetched despite a verdict"
    assert "verdict artifact" in capsys.readouterr().out


def test_a_lane_with_no_verdict_falls_back_to_the_job_log_and_says_so(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = wire(FakeGh(checks=[FAILED_CHECK], artifacts=[]))
    assert run_cli(monkeypatch, []) == 1
    out = capsys.readouterr().out
    assert "lane uploaded no verdict artifact — log tail" in out
    assert "ERROR: mutation failed for: app/api/v1/endpoints/bot.py" in out
    assert "actions/jobs/1234/logs" in " ".join(fake.calls)


def test_an_external_check_says_to_open_the_url_rather_than_inventing_a_source(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    external = dict(
        FAILED_CHECK,
        name="SonarCloud",
        html_url="https://github.com/o/r/runs/9",
        app={"slug": "sonarcloud"},
    )
    wire(FakeGh(checks=[external]))
    run_cli(monkeypatch, [])
    out = capsys.readouterr().out
    assert "external check (sonarcloud) — open the URL" in out
    assert "https://github.com/o/r/runs/9" in out


def test_a_matrix_jobs_artifact_name_still_matches_its_check() -> None:
    verdict: ci_remote.Verdict = {"lane": "test-python", "artifact": "verdict-test-python-unit-a"}
    assert ci_remote.verdict_matches(verdict, "test-python (unit-a)")
    assert not ci_remote.verdict_matches(verdict, "test-typescript")


def test_a_failing_verdict_whose_lane_matches_no_check_is_still_printed(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    orphan = dict(VERDICT, lane="dead-code", summary="3 unused exports")
    wire(
        FakeGh(
            checks=[FAILED_CHECK],
            artifacts=[{"id": 55, "name": "verdict-dead-code", "expired": False}],
            zip_blob=verdict_zip(orphan),
        )
    )
    run_cli(monkeypatch, [])
    out = capsys.readouterr().out
    assert "a lane failed inside a passing job" in out
    assert "3 unused exports" in out


# -------------------------------------------------------------------- output discipline


def test_a_green_pr_prints_a_header_and_nothing_that_looks_like_a_failure(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire(FakeGh(checks=[PASSED_CHECK]))
    assert run_cli(monkeypatch, []) == 0
    out = capsys.readouterr().out
    assert "PR #7 feat: a thing" in out
    assert "checks: 1 pass / 0 fail / 0 pending / 0 skipped" in out
    assert "FAIL" not in out and "PEND" not in out
    assert "Nothing blocking on GitHub's side" in out


def test_advice_is_deduplicated_across_verdicts(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    second = dict(VERDICT, lane="mutation-shard-4")
    wire(
        FakeGh(
            checks=[FAILED_CHECK],
            artifacts=[{"id": 55, "name": "verdict-mutation-shard-3", "expired": False}],
            zip_blob=verdict_zip(VERDICT, second),
        )
    )
    run_cli(monkeypatch, [])
    out = capsys.readouterr().out
    assert out.count("Reproduce with `mise mutation:replay") == 1


def test_a_conflicting_pr_is_red_even_with_green_checks(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire(FakeGh(checks=[PASSED_CHECK], pr_meta=dict(PR_META, mergeable="CONFLICTING")))
    assert run_cli(monkeypatch, []) == 1
    assert "git merge origin/master" in capsys.readouterr().out


# -------------------------------------------------------------------------------- stack


STACK: dict[str, Any] = {
    "trunk": "master",
    "currentBranch": "feat/thing",
    "branches": [
        {"name": "feat/base", "isCurrent": False, "pr": {"number": 6}},
        {"name": "feat/thing", "isCurrent": True, "pr": {"number": 7}},
    ],
}


def stack_rollup(*prs: tuple[int, str]) -> dict[str, Any]:
    one_green_check = {
        "nodes": [
            {
                "commit": {
                    "statusCheckRollup": {
                        "contexts": {
                            "nodes": [
                                {
                                    "__typename": "CheckRun",
                                    "status": "COMPLETED",
                                    "conclusion": "SUCCESS",
                                }
                            ]
                        }
                    }
                }
            }
        ]
    }
    return {
        "data": {
            "repository": {
                f"p{n}": {"number": n, "baseRefName": base, "commits": one_green_check}
                for n, base in prs
            }
        }
    }


@pytest.fixture
def stacked(wire, monkeypatch: pytest.MonkeyPatch):
    """Set up a two-PR stack whose second GraphQL call returns the rollup payload."""

    def install(*prs: tuple[int, str]) -> FakeGh:
        fake = FakeGh(checks=[PASSED_CHECK])
        wire(fake, stack=STACK)
        rollup = json.dumps(stack_rollup(*prs))
        seen = {"graphql": 0}

        def router(
            args: list[str], timeout_s: int, stdin_text: str | None = None
        ) -> tuple[int, str, str]:
            if args[1] == "graphql":
                seen["graphql"] += 1
                if seen["graphql"] > 1:  # first is PR state, second is the stack rollup
                    return 0, rollup, ""
            return fake.text(args, timeout_s, stdin_text)

        monkeypatch.setattr(ci_remote, "gh", router)
        return fake

    return install


def test_the_stack_lists_every_pr_with_its_base_and_marks_the_current_one(
    stacked, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stacked((6, "master"), (7, "feat/base"))
    run_cli(monkeypatch, [])
    out = capsys.readouterr().out
    assert "   #6 feat/base" in out
    assert " * #7 feat/thing" in out
    assert "-> feat/base  ?  ?/?  0 threads  1 pass / 0 fail / 0 pending  greptile —" in out
    assert "WARNING" not in out


def test_a_pr_targeting_master_instead_of_its_stack_parent_is_warned_about(
    stacked, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stacked((6, "master"), (7, "master"))  # #7 should target feat/base
    run_cli(monkeypatch, [])
    out = capsys.readouterr().out
    assert "GitHub base is 'master' but the stack parent is 'feat/base'" in out
    assert "diff-scoped gate" in out
    assert "gh pr edit 7 --base feat/base" in out


def test_no_stack_skips_the_section_entirely(
    stacked, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stacked((6, "master"), (7, "master"))
    run_cli(monkeypatch, ["--no-stack"])
    assert "STACK" not in capsys.readouterr().out


# --------------------------------------------------------------------------------- json


def test_json_carries_the_pr_checks_verdicts_and_fallback_tails(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire(
        FakeGh(
            checks=[FAILED_CHECK, PASSED_CHECK],
            artifacts=[{"id": 55, "name": "verdict-mutation-shard-3", "expired": False}],
            zip_blob=verdict_zip(VERDICT),
        )
    )
    assert run_cli(monkeypatch, ["--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == ci_remote.SCHEMA_VERSION
    assert report["pr"]["number"] == 7
    assert report["pr"]["title"] == "feat: a thing"
    assert report["pr"]["base"] == "master"
    assert report["counts"] == {
        "passed": 1,
        "failed": 1,
        "pending": 0,
        "skipped": 0,
        "error": 0,
        "timeout": 0,
    }
    assert report["verdicts"][0]["lane"] == "mutation-shard-3"
    assert report["verdicts"][0]["artifact"] == "verdict-mutation-shard-3"
    assert report["fallback_tails"] == {}
    assert report["sources"][FAILED_CHECK["name"]] == "verdict artifact verdict-mutation-shard-3"
    assert report["advice"][0].startswith("Reproduce with")


def test_json_carries_the_fallback_tail_when_there_is_no_verdict(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire(FakeGh(checks=[FAILED_CHECK]))
    run_cli(monkeypatch, ["--json"])
    report = json.loads(capsys.readouterr().out)
    tail = report["fallback_tails"][FAILED_CHECK["name"]]
    assert tail[-1] == "ERROR: Process completed with exit code 1."
    assert report["verdicts"] == []


def test_json_prints_nothing_but_json(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire(FakeGh(checks=[PASSED_CHECK]))
    run_cli(monkeypatch, ["--json"])
    json.loads(capsys.readouterr().out)  # raises if a human line leaked onto stdout


# ----------------------------------------------------------------------- fault injection


def test_a_pending_check_is_not_a_failure(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pending = dict(PASSED_CHECK, name="docker-image", status="in_progress", conclusion=None)
    wire(FakeGh(checks=[pending]))
    assert run_cli(monkeypatch, []) == 0
    out = capsys.readouterr().out
    assert "PEND  docker-image" in out
    assert "1 check still running" in out


def test_an_auth_failure_names_the_endpoint_and_exits_one(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire(FakeGh(checks=[]))
    monkeypatch.setattr(
        ci_remote, "gh", lambda *_a, **_k: (4, "", "gh: Bad credentials (HTTP 401)")
    )
    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, [])
    assert exc.value.code == 1
    assert "POST /graphql (pull request state) failed" in capsys.readouterr().err


def test_a_graphql_errors_payload_exits_two_without_a_traceback(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire(FakeGh(checks=[]))
    monkeypatch.setattr(
        ci_remote, "gh", lambda *_a, **_k: (0, json.dumps({"errors": [{"message": "nope"}]}), "")
    )
    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, [])
    assert exc.value.code == 2
    assert "GraphQL errors (pull request state)" in capsys.readouterr().err


def test_a_missing_job_log_says_so_instead_of_printing_an_empty_section(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire(FakeGh(checks=[FAILED_CHECK]))
    monkeypatch.setattr(ci_remote, "gh_bytes", lambda *_a, **_k: (1, b"", "HTTP 404: Not Found"))
    assert run_cli(monkeypatch, []) == 1
    out = capsys.readouterr().out
    assert "no log yet" in out
    assert "logs appear once the run completes" in out


def test_an_aggregate_gate_job_gets_its_own_log_not_another_lanes_verdict(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`Quality gate (required)` slugs to no lane, so it has no verdict of its own.

    Pointing it at whatever else on the run happened to fail is misdirection —
    it once sent six mutation shards to python-static's verdict. Its log tail
    is the lane table, which names the lane that took the gate down.
    """
    gate = dict(FAILED_CHECK, name="Quality gate (required)")
    gate_log = (
        "2026-09-10T21:52:33.9375589Z   test-mutation:         failure\n"
        "2026-09-10T21:52:33.9393569Z ##[error]lane 'test-mutation' did not pass\n"
    )
    fake = wire(
        FakeGh(
            checks=[gate],
            artifacts=[{"id": 55, "name": "verdict-python-static", "expired": False}],
            zip_blob=verdict_zip(dict(VERDICT, lane="python-static")),
            job_log=gate_log,
        )
    )
    assert run_cli(monkeypatch, []) == 1
    out = capsys.readouterr().out
    assert "no failing verdict in this run's artifacts — log tail" in out
    assert "ERROR: lane 'test-mutation' did not pass" in out
    assert any(c.endswith("/logs") for c in fake.calls)
    # python-static's verdict still shows, but as its own unmatched lane.
    assert "a lane failed inside a passing job" in out


def test_a_red_lane_with_no_verdict_never_reads_as_nothing_blocking(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Advice was empty when only no-verdict failures existed, so a red PR read as clean."""
    wire(FakeGh(checks=[FAILED_CHECK]))
    assert run_cli(monkeypatch, []) == 1
    out = capsys.readouterr().out
    assert "Nothing blocking" not in out
    assert "1 lane failed with no verdict artifact" in out
    assert "upload-verdict" in out


def test_the_shown_tail_is_trimmed_but_json_keeps_the_whole_window(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    long_log = "".join(f"2026-09-10T21:39:26.626{i:04d}Z step {i}\n" for i in range(60))
    long_log += "2026-09-10T21:39:26.6270852Z ##[error]Process completed with exit code 1.\n"
    wire(FakeGh(checks=[FAILED_CHECK], job_log=long_log))
    run_cli(monkeypatch, [])
    shown = capsys.readouterr().out
    assert "step 41" in shown and "step 40" not in shown  # last 20 of the 40-line window
    assert f"… {ci_remote.FALLBACK_TAIL_LINES - ci_remote.SHOWN_TAIL_LINES} earlier lines" in shown

    wire(FakeGh(checks=[FAILED_CHECK], job_log=long_log))
    run_cli(monkeypatch, ["--json"])
    tail = json.loads(capsys.readouterr().out)["fallback_tails"][FAILED_CHECK["name"]]
    assert len(tail) == ci_remote.FALLBACK_TAIL_LINES


# The artifact set PR #1161 run 34584038269 actually produced: one
# `verdict-test-mutation-<i>` per shard, each holding a single `mutation/shard-<i>`
# verdict with status `pass` — written before the shard's job went on to fail.
# Nothing in the run's artifacts says why any shard is red.
SHARD_ARTIFACTS = [
    {"id": 1000 + i, "name": f"verdict-test-mutation-{i}", "expired": False} for i in range(4)
]
SHARD_BLOBS = {
    1000 + i: verdict_zip({"lane": f"mutation/shard-{i}", "status": "pass", "summary": "passed"})
    for i in range(4)
}
SHARD_CHECKS = [
    dict(
        FAILED_CHECK,
        name=f"Mutation shard {i + 1}/6 (19 modules)",
        conclusion="failure" if i == 0 else "success",
        html_url=f"https://github.com/o/r/actions/runs/99/job/{1234 + i}",
    )
    for i in range(4)
]


def test_a_passing_shard_verdict_is_never_printed_as_a_failure(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`mutation/shard-1` (pass) prefix-matches the red check `Mutation shard 1/6`.

    It used to render as `FAIL mutation/shard-1 [pass]` and, worse, count as
    the check's explanation — so the log tail that held the real reason was
    never fetched.
    """
    wire(FakeGh(checks=SHARD_CHECKS, artifacts=SHARD_ARTIFACTS, zip_blobs=SHARD_BLOBS))
    assert run_cli(monkeypatch, []) == 1
    out = capsys.readouterr().out
    assert "[pass]" not in out
    assert "FAIL  mutation/shard-" not in out
    headers = [line for line in out.splitlines() if line.startswith("FAIL  ")]
    assert headers == [
        "FAIL  Mutation shard 1/6 (19 modules)  [failed]  "
        "(no failing verdict in this run's artifacts — log tail)"
    ]


def test_a_red_check_with_only_passing_verdicts_falls_back_to_the_log_and_says_so(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = wire(FakeGh(checks=SHARD_CHECKS, artifacts=SHARD_ARTIFACTS, zip_blobs=SHARD_BLOBS))
    run_cli(monkeypatch, [])
    out = capsys.readouterr().out
    assert "no failing verdict in this run's artifacts — log tail" in out
    assert "see the lanes below" not in out, "there are no failing lanes below to see"
    assert "ERROR: mutation failed for: app/api/v1/endpoints/bot.py" in out
    assert "actions/jobs/1234/logs" in " ".join(fake.calls)


def test_the_lane_uploaded_nothing_wording_is_reserved_for_a_run_with_no_verdicts(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire(FakeGh(checks=[FAILED_CHECK], artifacts=[]))
    run_cli(monkeypatch, [])
    assert "lane uploaded no verdict artifact — log tail" in capsys.readouterr().out


# Run 34586506166 (PR #1175): `Mutation shard 3/6 (21 modules)` is red, and the
# only artifact that explains it is `verdict-test-mutation-2` — matrix value 2,
# which no slug of "Mutation shard 3/6" will ever produce. It carries 21
# per-module verdicts (one `fail` with a file:line) plus a `mutation/shard-2`
# rollup whose summary is a pointer to the log and nothing else.
SHARD_3_CHECK: dict[str, Any] = {
    "name": "Mutation shard 3/6 (21 modules)",
    "status": "completed",
    "conclusion": "failure",
    "html_url": "https://github.com/o/r/actions/runs/99/job/1234",
    "app": {"slug": "github-actions"},
}
CONVERSATION_SERVICE_VERDICT: dict[str, Any] = {
    "lane": "mutation/app/services/conversation_service.py",
    "status": "fail",
    "summary": "1 changed line(s) no test reaches in app/services/conversation_service.py",
    "findings": [
        {
            "file": "apps/api/app/services/conversation_service.py",
            "line": 446,
            "message": "no mapped test executes this changed line, so no mutant on it could ever be killed",
        }
    ],
    "advice": [
        "Write a test that executes apps/api/app/services/conversation_service.py:446 "
        "and asserts what it does."
    ],
}
SHARD_2_ROLLUP: dict[str, Any] = {
    "lane": "mutation/shard-2",
    "status": "fail",
    "summary": "the lane failed and has not adopted the verdict contract — "
    "its reason is only in this job's log",
    "findings": [],
    "advice": ["Open this job's log."],
}
SHARD_2_PASS: dict[str, Any] = {
    "lane": "mutation/app/core/stream_manager.py",
    "status": "pass",
    "summary": "every mutant on the changed lines of app/core/stream_manager.py was killed",
    "findings": [],
}


def wire_shard_3(wire) -> FakeGh:
    return wire(
        FakeGh(
            checks=[SHARD_3_CHECK],
            artifacts=[{"id": 77, "name": "verdict-test-mutation-2", "expired": False}],
            zip_blob=verdict_zip(SHARD_2_PASS, CONVERSATION_SERVICE_VERDICT, SHARD_2_ROLLUP),
        )
    )


def test_a_shards_verdicts_are_attributed_to_it_by_matrix_index(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = wire_shard_3(wire)
    assert run_cli(monkeypatch, []) == 1
    out = capsys.readouterr().out
    assert (
        "FAIL  Mutation shard 3/6 (21 modules)  [failed]  (verdict artifact verdict-test-mutation-2)"
        in out
    )
    assert "mutation/app/services/conversation_service.py  [fail]" in out
    assert "apps/api/app/services/conversation_service.py:446 — no mapped test executes" in out
    # It is the check's own finding now, not a stray.
    assert "no matching check run" not in out
    # And the log tail is not needed.
    assert not any(c.endswith("/logs") for c in fake.calls)


def test_the_content_free_shard_rollup_does_not_bury_the_finding(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire_shard_3(wire)
    run_cli(monkeypatch, [])
    out = capsys.readouterr().out
    assert "its reason is only in this job's log" not in out
    assert "mutation/shard-2" not in out
    assert "Open this job's log." not in out
    assert "Write a test that executes" in out  # the real advice survives


def test_a_passing_per_module_verdict_stays_out_of_the_failure_section(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire_shard_3(wire)
    run_cli(monkeypatch, [])
    out = capsys.readouterr().out
    assert "stream_manager" not in out


def test_matrix_index_matching_needs_a_shared_word_not_just_a_number() -> None:
    """`verdict-anything-else-2` must not claim `Mutation shard 3/6`."""
    assert ci_remote.matrix_index("Mutation shard 3/6 (21 modules)") == 2
    assert ci_remote.matrix_index("Quality gate (required)") is None
    assert ci_remote.artifact_index("verdict-test-mutation-2") == ("test-mutation", 2)
    assert ci_remote.artifact_index("verdict-test-mutation-plan") is None

    right = {"lane": "mutation/x.py", "artifact": "verdict-test-mutation-2"}
    wrong_name = {"lane": "other/x.py", "artifact": "verdict-unrelated-thing-2"}
    wrong_index = {"lane": "mutation/x.py", "artifact": "verdict-test-mutation-4"}
    assert ci_remote.verdict_matches(right, "Mutation shard 3/6 (21 modules)")
    assert not ci_remote.verdict_matches(wrong_name, "Mutation shard 3/6 (21 modules)")
    assert not ci_remote.verdict_matches(wrong_index, "Mutation shard 3/6 (21 modules)")


# --------------------------------------------------------------- mutation shard records

# What run 34586506166's `mutation-log-2` artifact holds: shard.verdict.json's
# per-module records beside the shard.log they were read from. The log is the
# only thing that separates "mutmut died" from "the suite is weak".
NO_STATE_LOG = (
    "app/services/x.py\n"
    "E       Failed: Timeout >45.0s\n"
    "E       Failed: Timeout >45.0s\n"
    "MUTATION RUN FAILED (no state produced) — see mutmut's output above.\n"
)
SURVIVOR_LOG = "MUTATION FAILED — 1 mutant survived\n"

ERROR_MODULE: dict[str, Any] = {
    "module": "app/services/x.py",
    "path": "apps/api/app/services/x.py",
    "status": "error",
    "survivors": [],
    "gap_lines": [],
    "reason": "app/services/x.py exited 1 without reaching a verdict — see shard.log",
}
SURVIVOR_MODULE: dict[str, Any] = {
    "module": "app/services/y.py",
    "path": "apps/api/app/services/y.py",
    "status": "survivors",
    "survivors": [
        {
            "name": "y_ǁCǁm__mutmut_13",
            "function": "charge",
            "file": "apps/api/app/services/y.py",
            "line": 212,
            "change": "`amount > 0` -> `amount >= 0`",
            "diff": "",
        }
    ],
    "gap_lines": [],
    "reason": None,
}


def shard_zip(modules: list[dict[str, Any]], log: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("shard.verdict.json", json.dumps({"modules": modules}))
        archive.writestr("shard.log", log)
    return buffer.getvalue()


def wire_shard_record(wire, modules: list[dict[str, Any]], log: str) -> FakeGh:
    return wire(
        FakeGh(
            checks=[SHARD_3_CHECK],
            artifacts=[{"id": 88, "name": "mutation-log-2", "expired": False}],
            zip_blobs={88: shard_zip(modules, log)},
        )
    )


def test_a_shard_that_produced_no_state_says_so_and_says_it_is_safe_to_rerun(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An errored module used to read like a test gap; it is an oversubscribed box."""
    fake = wire_shard_record(wire, [ERROR_MODULE], NO_STATE_LOG)
    assert run_cli(monkeypatch, []) == 1
    out = capsys.readouterr().out
    assert "(shard record mutation-log-2)" in out
    assert (
        "app/services/x.py  error — mutmut produced no state (2 tests hit the per-test timeout); "
        "no survivors; safe to re-run" in out
    )
    assert "its reason is only in this job's log" not in out
    assert not any(c.endswith("/logs") for c in fake.calls), "log fetched despite a shard record"
    assert "--rerun-timeouts" in out


def test_a_survivor_names_the_line_and_the_change_rather_than_the_mutant_id(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire_shard_record(wire, [SURVIVOR_MODULE], SURVIVOR_LOG)
    run_cli(monkeypatch, [])
    out = capsys.readouterr().out
    assert (
        "app/services/y.py  survivors: apps/api/app/services/y.py:212 — "
        "`amount > 0` -> `amount >= 0`" in out
    )
    # A survivor is never safe to re-run, so the offer must not appear.
    assert "--rerun-timeouts" not in out


def test_a_passing_module_stays_out_of_the_shard_record_section(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    passed = dict(ERROR_MODULE, module="app/core/ok.py", status="pass")
    wire_shard_record(wire, [passed, ERROR_MODULE], NO_STATE_LOG)
    run_cli(monkeypatch, [])
    assert "app/core/ok.py" not in capsys.readouterr().out


def test_rerun_timeouts_reruns_the_failed_jobs_when_nothing_survived(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = wire_shard_record(wire, [ERROR_MODULE], NO_STATE_LOG)
    reruns: list[list[str]] = []

    def router(
        args: list[str], timeout_s: int, stdin_text: str | None = None
    ) -> tuple[int, str, str]:
        if args[0] == "run":
            reruns.append(args)
            return 0, "", ""
        return fake.text(args, timeout_s, stdin_text)

    monkeypatch.setattr(ci_remote, "gh", router)
    assert run_cli(monkeypatch, ["--rerun-timeouts"]) == 0
    assert reruns == [["run", "rerun", "99", "--failed"]]
    assert "re-ran the failed jobs of run 99" in capsys.readouterr().out


def test_rerun_timeouts_refuses_when_a_mutant_actually_survived(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A re-run cannot turn a surviving mutant green; it only spends the box."""
    fake = wire_shard_record(wire, [SURVIVOR_MODULE], SURVIVOR_LOG)

    def router(
        args: list[str], timeout_s: int, stdin_text: str | None = None
    ) -> tuple[int, str, str]:
        assert args[0] != "run", "rerun issued for a surviving mutant"
        return fake.text(args, timeout_s, stdin_text)

    monkeypatch.setattr(ci_remote, "gh", router)
    assert run_cli(monkeypatch, ["--rerun-timeouts"]) == 1
    out = capsys.readouterr().out
    assert "refusing" in out
    assert "Mutation shard 3/6 (21 modules)" in out


def test_rerun_timeouts_refuses_when_one_module_died_and_another_had_a_survivor(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A shard can produce no state for one module and still prove a test gap in another."""
    fake = wire_shard_record(wire, [ERROR_MODULE, SURVIVOR_MODULE], NO_STATE_LOG)

    def router(
        args: list[str], timeout_s: int, stdin_text: str | None = None
    ) -> tuple[int, str, str]:
        assert args[0] != "run", "rerun issued for a shard that also had a survivor"
        return fake.text(args, timeout_s, stdin_text)

    monkeypatch.setattr(ci_remote, "gh", router)
    assert run_cli(monkeypatch, ["--rerun-timeouts"]) == 1
    assert "refusing" in capsys.readouterr().out


def test_rerun_timeouts_on_a_green_pr_reruns_nothing(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire(FakeGh(checks=[PASSED_CHECK]))
    assert run_cli(monkeypatch, ["--rerun-timeouts"]) == 0
    assert "nothing is failing" in capsys.readouterr().out


# --------------------------------------------------------------------------- stack mode

GREPTILE_BODY = (
    '<h2><a href="https://app.greptile.com/api/retrigger?id=1">x</a>Confidence Score: 4/5</h2>\n'
    "<sub>Reviews (1) · Last reviewed commit: "
    '["feat: a thing"](https://github.com/o/r/commit/abc123def4567890)</sub>'
)


def rich_pr(number: int, base: str, head: str) -> dict[str, Any]:
    """One stack PR as the enriched GraphQL returns it."""
    return {
        "number": number,
        "baseRefName": base,
        "headRefOid": head,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "BLOCKED",
        "reviewThreads": {"nodes": [{"isResolved": False}, {"isResolved": True}]},
        "comments": {
            "nodes": [
                {"author": {"login": "coderabbitai"}, "body": "Confidence Score: 1/5"},
                {"author": {"login": "greptile-apps"}, "body": GREPTILE_BODY},
            ]
        },
        "commits": {
            "nodes": [
                {
                    "commit": {
                        "statusCheckRollup": {
                            "contexts": {
                                "nodes": [
                                    {
                                        "__typename": "CheckRun",
                                        "name": "biome",
                                        "status": "COMPLETED",
                                        "conclusion": "FAILURE",
                                    },
                                    {
                                        "__typename": "CheckRun",
                                        "name": "dead-code",
                                        "status": "COMPLETED",
                                        "conclusion": "SUCCESS",
                                    },
                                ]
                            }
                        }
                    }
                }
            ]
        },
    }


@pytest.fixture
def rich_stack(wire, monkeypatch: pytest.MonkeyPatch):
    """Set up a two-PR stack whose rollup carries merge state, threads, lanes and Greptile."""

    def install(*prs: tuple[int, str, str]) -> FakeGh:
        fake = FakeGh(checks=[PASSED_CHECK])
        wire(fake, stack=STACK)
        payload = json.dumps(
            {"data": {"repository": {f"p{n}": rich_pr(n, b, h) for n, b, h in prs}}}
        )

        def router(
            args: list[str], timeout_s: int, stdin_text: str | None = None
        ) -> tuple[int, str, str]:
            # The stack query is the one asking for mergeStateStatus; the PR-state
            # query never does. Counting calls would mis-route --stack, which
            # makes no PR-state call at all.
            if args[1] == "graphql" and "mergeStateStatus" in (stdin_text or ""):
                return 0, payload, ""
            return fake.text(args, timeout_s, stdin_text)

        monkeypatch.setattr(ci_remote, "gh", router)
        return fake

    return install


def test_stack_mode_prints_one_line_per_pr_with_everything_needed_to_pick_one(
    rich_stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rich_stack((6, "master", "abc123def4567890"), (7, "feat/base", "abc123def4567890"))
    assert run_cli(monkeypatch, ["--stack"]) == 1  # biome is red on both
    out = capsys.readouterr().out
    assert " * #7 feat/thing" in out
    assert "abc123def" in out
    assert "MERGEABLE/BLOCKED" in out
    assert "1 thread" in out
    assert "1 pass / 1 fail / 0 pending" in out
    assert "greptile 4/5 @abc123def" in out
    assert "failing: biome" in out
    # Stack mode is the stack and nothing else.
    assert "PR #7 feat: a thing" not in out
    assert "ADVICE" not in out


def test_a_greptile_score_against_an_older_commit_is_marked_stale(
    rich_stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A 4/5 on a sha two pushes old says nothing about the head."""
    rich_stack((6, "master", "0000000000000000"), (7, "feat/base", "0000000000000000"))
    run_cli(monkeypatch, ["--stack"])
    assert "greptile 4/5 @abc123def STALE" in capsys.readouterr().out


def test_stack_json_carries_the_same_fields_the_line_shows(
    rich_stack, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rich_stack((6, "master", "abc123def4567890"), (7, "feat/base", "abc123def4567890"))
    run_cli(monkeypatch, ["--stack", "--json"])
    report = json.loads(capsys.readouterr().out)
    row = next(r for r in report["stack"] if r["pr"] == 7)
    assert row["head_sha"] == "abc123def4567890"
    assert row["mergeable"] == "MERGEABLE"
    assert row["merge_state_status"] == "BLOCKED"
    assert row["unresolved_threads"] == 1
    assert row["counts"]["passed"] == 1
    assert row["counts"]["failed"] == 1
    assert row["failing_lanes"] == ["biome"]
    assert row["greptile"] == {
        "score": 4,
        "out_of": 5,
        "commit": "abc123def4567890",
        "commit_url": "https://github.com/o/r/commit/abc123def4567890",
    }


def test_stack_mode_refuses_to_be_combined_with_another_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, ["--stack", "--watch"])
    assert exc.value.code == 2
    assert "its own mode" in capsys.readouterr().err


# ------------------------------------------------------------------------ runner health


def health(**over: Any) -> dict[str, Any]:
    """`runner.sh health` output for a box with room to spare."""
    base: dict[str, Any] = {
        "is_runner_host": True,
        "listeners": {"online": 11, "busy": 3, "idle": 8, "registered": 11},
        "loadavg": {"1m": 4.0, "5m": 5.0, "15m": 6.0},
        "threads": 16,
        "cpu_slots": {"dir": "/run/gaia-ci/cpu-slots", "total": 16, "held": 4, "available": 12},
        "processes": {"mutmut": 1, "pytest": 2, "runner_listeners": 11},
    }
    return {**base, **over}


def test_a_queued_lane_on_a_thrashing_box_says_the_box_is_the_problem(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Load far above the thread count is a box to wait for, not a pool to grow."""
    wire(FakeGh(checks=[PASSED_CHECK]))
    loaded = health(loadavg={"1m": 31.0, "5m": 28.0, "15m": 24.0})
    monkeypatch.setattr(ci_remote, "runner_health", lambda: loaded)
    run_cli(monkeypatch, [])
    out = capsys.readouterr().out
    assert "BOX: BOX OVERSUBSCRIBED" in out
    assert "load 31.0/28.0/24.0 on 16 threads" in out
    assert "cpu slots 4/16 held" in out
    assert "1 mutmut, 2 pytest" in out


def test_a_quiet_box_with_every_listener_busy_blames_the_github_pool(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The opposite cause, and the opposite fix: more listeners, not less load."""
    wire(FakeGh(checks=[PASSED_CHECK]))
    saturated = health(listeners={"online": 11, "busy": 11, "idle": 0, "registered": 11})
    monkeypatch.setattr(ci_remote, "runner_health", lambda: saturated)
    run_cli(monkeypatch, [])
    out = capsys.readouterr().out
    assert "GITHUB POOL SATURATED" in out
    assert "BOX OVERSUBSCRIBED" not in out


def test_a_box_with_room_says_so_rather_than_implying_a_problem(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire(FakeGh(checks=[PASSED_CHECK]))
    monkeypatch.setattr(ci_remote, "runner_health", lambda: health())
    run_cli(monkeypatch, [])
    assert "BOX: box has headroom" in capsys.readouterr().out


def test_off_the_box_the_line_is_absent_rather_than_empty(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A laptop's load average says nothing about CI, so it says nothing."""
    wire(FakeGh(checks=[PASSED_CHECK]))
    run_cli(monkeypatch, [])
    assert "BOX:" not in capsys.readouterr().out


def test_runner_health_stays_silent_when_the_host_is_not_the_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The script answers `is_runner_host: false` off the box; that is a None here."""

    class Proc:
        returncode = 0
        stdout = json.dumps(health(is_runner_host=False))

    monkeypatch.setattr(ci_remote.subprocess, "run", lambda *_a, **_k: Proc())
    assert ci_remote.runner_health() is None


def test_a_health_probe_that_fails_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A diagnostic must never be able to fail the command it is decorating."""

    class Proc:
        returncode = 2
        stdout = "not json"

    monkeypatch.setattr(ci_remote.subprocess, "run", lambda *_a, **_k: Proc())
    assert ci_remote.runner_health() is None


# Run 35128539215 (PR #1241): every shard produced "no state", nothing
# survived, and NOT ONE test hit the per-test timeout — the suite simply
# failed inside the mutation workdir with an AssertionError. Reading that as
# "safe to re-run" is a wrong answer that costs half an hour of the box.
NO_TIMEOUT_LOG = (
    "MUTATION RUN FAILED (no state produced) — see mutmut's output above.\n"
    "AssertionError: assert [] == ['unknown']\n"
)


def test_no_state_without_a_single_timeout_is_not_safe_to_rerun(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = wire_shard_record(wire, [ERROR_MODULE], NO_TIMEOUT_LOG)
    assert run_cli(monkeypatch, []) == 1
    out = capsys.readouterr().out
    assert "no test hit the per-test timeout" in out
    assert "a re-run will not help" in out
    assert "safe to re-run" not in out
    assert "--rerun-timeouts" not in out
    assert fake  # the artifact was read rather than the job log


def test_rerun_timeouts_refuses_a_shard_that_never_hit_the_timeout(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = wire_shard_record(wire, [ERROR_MODULE], NO_TIMEOUT_LOG)

    def router(
        args: list[str], timeout_s: int, stdin_text: str | None = None
    ) -> tuple[int, str, str]:
        assert args[0] != "run", "rerun issued for a shard whose suite simply failed"
        return fake.text(args, timeout_s, stdin_text)

    monkeypatch.setattr(ci_remote, "gh", router)
    assert run_cli(monkeypatch, ["--rerun-timeouts"]) == 1
    assert "refusing" in capsys.readouterr().out


def test_only_the_newest_upload_of_a_shard_name_is_read(
    wire, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`gh run rerun --failed` re-uploads the same artifact NAME into the same run.

    Run 35128539215 carried three generations of four shards, the older ones
    with zero modules; reading the first match printed the empty one.
    """
    wire(
        FakeGh(
            checks=[SHARD_3_CHECK],
            artifacts=[
                {
                    "id": 1,
                    "name": "mutation-log-2",
                    "expired": False,
                    "created_at": "2026-09-16T19:19:00Z",
                },
                {
                    "id": 2,
                    "name": "mutation-log-2",
                    "expired": False,
                    "created_at": "2026-09-16T21:04:50Z",
                },
            ],
            zip_blobs={
                1: shard_zip([], ""),
                2: shard_zip([SURVIVOR_MODULE], SURVIVOR_LOG),
            },
        )
    )
    run_cli(monkeypatch, [])
    out = capsys.readouterr().out
    assert "app/services/y.py  survivors:" in out
    assert "log tail" not in out, "the stale empty upload won and sent the reader to the log"
