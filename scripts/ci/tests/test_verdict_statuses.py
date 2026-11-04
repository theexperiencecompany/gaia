"""post-statuses: one commit status per check inside a grouped lane.

ci.yml folds a dozen checks into one job each (lint-node, lint-python,
lint-mixed, scan), so the checks list shows the job, not biome or mypy. Each
check's outcome — its nx tasks' results, or its step's for a check an action
runs — is posted back as its own `ci / <area> / <check>` status pointing at the
job, so a red biome reads as `ci / node / biome` on the PR. A status that says
success for a check that failed is the one outcome this must never produce, and
a status that failed to post must fail the step rather than vanish.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from github_fake import FakeGitHub, Reply
from lib import nx_affected
import pytest
import verdict

REPO = "theexperiencecompany/gaia"
SHA = "c9d667254c9d667254c9d667254c9d667254c9d6"
RUN = 4242
JOB_ID = 77
JOB_URL = f"https://github.com/{REPO}/actions/runs/{RUN}/job/{JOB_ID}"

STATUSES = rf"/repos/{REPO}/statuses/{SHA}$"
# Bound before the autouse fixture swaps it, for the invariant on the real graph.
REAL_CHECKS = nx_affected.checks


def _check(task: str, job: str, check: str, area: str, **extra: Any) -> nx_affected.Check:
    return nx_affected.Check(
        task=task, job=job, check=check, area=area, events=None, branch=None,
        reuse=True, runner=extra.pop("runner", "nx"), **extra,
    )  # fmt: skip


FAKE_CHECKS = {
    c.task: c
    for c in [
        _check("ci:biome", "lint-node", "biome", "node"),
        _check("ci:deps", "lint-node", "deps", "node", fallback="package.json"),
        _check("web:type-check", "lint-node", "type-check", "node"),
        _check("cli:type-check", "lint-node", "type-check", "node"),
        _check("ci:ruff", "lint-python", "ruff", "python"),
        _check("ci:lint-imports", "lint-python", "lint-imports", "python", cwd="apps/api"),
        _check("ci:gitleaks", "repo-policy", "gitleaks", "security", runner="action"),
        _check("web:build", "ts-build-test", "build", "build"),
    ]
}


@pytest.fixture(autouse=True)
def _this_run(api: FakeGitHub, monkeypatch: pytest.MonkeyPatch) -> None:
    api.on("POST", STATUSES, Reply(201, {}))
    monkeypatch.delenv("GITHUB_SERVER_URL", raising=False)
    monkeypatch.setattr(nx_affected, "checks", lambda: FAKE_CHECKS)


def _post(
    tmp_path: Path,
    job: str,
    results: dict[str, str | nx_affected.TaskResult],
    *flags: str,
    planned: list[str] | None = None,
) -> int:
    """Run post-statuses for `job` with extra CLI `flags`; a bare status string is a result with no output."""
    path = tmp_path / "results.json"
    path.write_text(
        json.dumps(
            {
                task: {"status": r, "code": 0 if r == "success" else 1, "output": ""}
                if isinstance(r, str)
                else r
                for task, r in results.items()
            }
        )
    )
    argv = [
        "--job", job, "--results", str(path),
        "--job-tasks", json.dumps({job: list(results) if planned is None else planned}),
        "--repo", REPO, "--sha", SHA, "--run-id", str(RUN), "--job-id", str(JOB_ID),
    ]  # fmt: skip
    return verdict.cmd_post_statuses([*argv, *flags])


def _posted(api: FakeGitHub) -> list[dict[str, str]]:
    bodies: list[dict[str, str]] = []
    for req in api.requests:
        if req.method == "POST":
            assert isinstance(req.body, dict), req
            bodies.append({str(key): str(value) for key, value in req.body.items()})
    return bodies


def _statuses(api: FakeGitHub) -> dict[str, dict[str, str]]:
    return {fields["context"]: fields for fields in _posted(api)}


def _states(api: FakeGitHub) -> dict[str, str]:
    return {context: fields["state"] for context, fields in _statuses(api).items()}


def _job_verdict(tmp_path: Path, lane: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((tmp_path / "verdicts" / f"{lane}.json").read_text())
    return doc


def test_each_check_gets_its_own_status_on_the_head_sha(api: FakeGitHub, tmp_path: Path) -> None:
    assert _post(tmp_path, "lint-node", {"ci:biome": "success", "web:type-check": "failure"}) == 1

    assert {r.path for r in api.requests if r.method == "POST"} == {f"/repos/{REPO}/statuses/{SHA}"}
    assert _states(api) == {
        "ci / node / biome": "success",
        "ci / node / deps": "success",
        "ci / node / type-check": "failure",
    }


def test_a_failed_check_is_never_posted_as_success(api: FakeGitHub, tmp_path: Path) -> None:
    _post(tmp_path, "lint-node", {"ci:biome": "failure", "ci:deps": "local-cache"})

    assert _states(api)["ci / node / biome"] == "failure"
    assert _states(api)["ci / node / deps"] == "success"


def test_one_failed_task_fails_a_check_that_spans_several(api: FakeGitHub, tmp_path: Path) -> None:
    _post(tmp_path, "lint-node", {"web:type-check": "success", "cli:type-check": "failure"})

    assert _states(api)["ci / node / type-check"] == "failure"


def test_a_planned_task_with_no_result_fails_its_check_and_the_job(
    api: FakeGitHub, tmp_path: Path
) -> None:
    # nx could not start it, so it wrote no result: that is not "nothing to check".
    code = _post(tmp_path, "lint-node", {"ci:biome": "success"}, planned=["ci:biome", "ci:deps"])

    assert code == 1
    assert _states(api)["ci / node / deps"] == "failure"
    assert _job_verdict(tmp_path, "lint-node")["status"] == "fail"


def test_a_check_with_no_planned_task_is_skipped_and_passes(
    api: FakeGitHub, tmp_path: Path
) -> None:
    assert _post(tmp_path, "lint-node", {"ci:biome": "success"}) == 0

    assert _statuses(api)["ci / node / deps"]["description"].startswith("skipped")
    assert _job_verdict(tmp_path, "lint-node")["status"] == "pass"


def test_a_failed_task_writes_its_check_verdict_from_what_it_printed(tmp_path: Path) -> None:
    output = "tools/x.py:3:1: F401 [*] `os` imported but unused\nFound 1 error.\n"
    result: nx_affected.TaskResult = {"status": "failure", "code": 1, "output": output}

    assert _post(tmp_path, "lint-python", {"ci:ruff": result}, "--no-post") == 1

    findings = _job_verdict(tmp_path, "lint-python/ruff")["findings"]
    assert [(f["file"], f["line"]) for f in findings] == [("tools/x.py", 3)]
    assert "F401" in findings[0]["message"]


def test_a_check_run_from_a_subdirectory_reports_repo_relative_paths(tmp_path: Path) -> None:
    output = "app/agents/x.py:9:1: F401 `os` imported but unused\n"
    result: nx_affected.TaskResult = {"status": "failure", "code": 1, "output": output}

    _post(tmp_path, "lint-python", {"ci:lint-imports": result}, "--no-post")

    findings = _job_verdict(tmp_path, "lint-python/lint-imports")["findings"]
    assert [(f["file"], f["line"]) for f in findings] == [("apps/api/app/agents/x.py", 9)]


def test_a_passing_task_writes_no_check_verdict(tmp_path: Path) -> None:
    _post(tmp_path, "lint-python", {"ci:ruff": "success"}, "--no-post")

    assert not (tmp_path / "verdicts" / "lint-python" / "ruff.json").exists()


@pytest.mark.parametrize(
    ("step", "state"),
    [("gitleaks=failure", "failure"), ("gitleaks=cancelled", "error"), ("gitleaks=", "error")],
)
def test_an_action_checks_step_outcome_is_its_status(
    api: FakeGitHub, tmp_path: Path, step: str, state: str
) -> None:
    assert _post(tmp_path, "repo-policy", {}, "--step", step) == 1

    assert _states(api) == {"ci / security / gitleaks": state}


def test_an_action_check_whose_step_is_not_passed_is_skipped(
    api: FakeGitHub, tmp_path: Path
) -> None:
    assert _post(tmp_path, "repo-policy", {}) == 0

    assert _statuses(api)["ci / security / gitleaks"]["description"].startswith("skipped")


def test_every_status_links_to_the_job_that_ran_the_check(api: FakeGitHub, tmp_path: Path) -> None:
    _post(tmp_path, "lint-node", {"ci:biome": "success"})

    assert [r for r in api.requests if r.method == "GET"] == []
    assert _statuses(api)["ci / node / biome"]["target_url"] == JOB_URL


def test_a_jobs_api_lagging_behind_the_run_still_links_the_status_to_this_job(
    api: FakeGitHub, tmp_path: Path
) -> None:
    """Regression: in a GitHub Actions incident the jobs API showed running jobs queued, runnerless."""
    lagging = [{"runner_name": None, "status": "queued", "html_url": JOB_URL}]
    api.on("GET", r"/jobs$", Reply(body={"jobs": lagging}))

    assert _post(tmp_path, "lint-node", {"ci:biome": "success"}) == 0
    assert _statuses(api)["ci / node / biome"]["target_url"] == JOB_URL


def test_a_skipped_check_says_whether_it_was_reused_or_had_nothing_to_check(
    api: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # detect planned biome, but reuse-plan carried its earlier pass forward.
    code = _post(
        tmp_path,
        "lint-node",
        {},
        "--reused",
        json.dumps({"biome": "passed at abc1234 in run 7"}),
        planned=["ci:biome"],
    )

    assert code == 0
    statuses = _statuses(api)
    assert statuses["ci / node / biome"]["state"] == "success"
    assert statuses["ci / node / biome"]["description"].startswith("reused")
    assert "run 7" in statuses["ci / node / biome"]["description"]
    assert statuses["ci / node / deps"]["description"].startswith("skipped")
    assert "reused — passed at abc1234 in run 7" in capsys.readouterr().out


def test_an_unknown_task_result_is_not_a_pass(api: FakeGitHub, tmp_path: Path) -> None:
    assert _post(tmp_path, "lint-node", {"ci:biome": ""}) == 1

    assert _states(api)["ci / node / biome"] == "failure"


def test_a_long_reuse_note_fits_the_status_api_limit(api: FakeGitHub, tmp_path: Path) -> None:
    _post(
        tmp_path,
        "lint-node",
        {},
        "--reused",
        json.dumps({"biome": "x" * 400}),
        planned=["ci:biome"],
    )

    assert (
        len(_statuses(api)["ci / node / biome"]["description"]) <= verdict.STATUS_DESCRIPTION_LIMIT
    )


def test_a_post_that_keeps_failing_fails_the_step_after_trying_every_check(
    api: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api.on("POST", STATUSES, Reply(502, {"message": "bad gateway"}))

    assert _post(tmp_path, "lint-python", {"ci:ruff": "success"}) == 1
    # Both checks were attempted, each the client's full number of times.
    contexts = [fields["context"] for fields in _posted(api)]
    assert contexts == ["ci / python / lint-imports"] * 3 + ["ci / python / ruff"] * 3
    assert "2 status(es) never landed" in capsys.readouterr().out


def test_a_transient_post_failure_is_retried(api: FakeGitHub, tmp_path: Path) -> None:
    api.on("POST", STATUSES, Reply(502, {}), Reply(201, {}))

    assert _post(tmp_path, "repo-policy", {}, "--step", "gitleaks=success") == 0
    assert [fields["context"] for fields in _posted(api)] == [
        "ci / security / gitleaks",
        "ci / security / gitleaks",
    ]


def test_a_rejected_post_is_not_retried(api: FakeGitHub, tmp_path: Path) -> None:
    # A 422 is the request being wrong; repeating it cannot land the status.
    api.on("POST", STATUSES, Reply(422, {"message": "Validation Failed"}))

    assert _post(tmp_path, "repo-policy", {}, "--step", "gitleaks=success") == 1
    assert len(_posted(api)) == 1


COMMIT_STATUSES = rf"/repos/{REPO}/commits/{SHA}/statuses$"


def _recorded(context: str) -> dict[str, str]:
    return {
        "context": context, "state": "success",
        "description": "passed", "target_url": JOB_URL,
    }  # fmt: skip


def test_a_status_github_answered_500_to_but_recorded_counts_as_landed(
    api: FakeGitHub, tmp_path: Path
) -> None:
    """Regression: run 41888138270, every 500'd POST still created the status."""
    api.on("POST", STATUSES, Reply(500, {}))
    api.on(
        "GET", COMMIT_STATUSES, Reply(body=[]),
        Reply(body=[_recorded("ci / security / gitleaks")]),
    )  # fmt: skip

    assert _post(tmp_path, "repo-policy", {}, "--step", "gitleaks=success") == 0
    reads = [r for r in api.requests if r.method == "GET"]
    assert len(reads) == 2


def test_a_status_that_never_shows_on_read_back_fails_the_step(
    api: FakeGitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api.on("POST", STATUSES, Reply(500, {}))
    other = {**_recorded("ci / security / gitleaks"), "state": "failure"}
    api.on("GET", COMMIT_STATUSES, Reply(body=[other]))

    assert _post(tmp_path, "repo-policy", {}, "--step", "gitleaks=success") == 1
    assert len([r for r in api.requests if r.method == "GET"]) == verdict.STATUS_READ_BACKS
    assert "1 status(es) never landed: ci / security / gitleaks" in capsys.readouterr().out


def test_a_rejected_post_is_not_read_back(api: FakeGitHub, tmp_path: Path) -> None:
    api.on("POST", STATUSES, Reply(422, {"message": "Validation Failed"}))

    assert _post(tmp_path, "repo-policy", {}, "--step", "gitleaks=success") == 1
    assert [r for r in api.requests if r.method == "GET"] == []


def test_no_post_posts_nothing_but_still_decides_the_job(api: FakeGitHub, tmp_path: Path) -> None:
    assert _post(tmp_path, "lint-node", {"ci:deps": "failure"}, "--no-post") == 1

    assert _posted(api) == []
    assert "deps" in _job_verdict(tmp_path, "lint-node")["summary"]


def test_each_check_posts_under_its_area(api: FakeGitHub, tmp_path: Path) -> None:
    _post(tmp_path, "lint-python", {"ci:ruff": "success"})
    _post(tmp_path, "repo-policy", {}, "--step", "gitleaks=success")
    _post(tmp_path, "ts-build-test", {"web:build": "success"})

    assert sorted(_statuses(api)) == [
        "ci / build / build",
        "ci / python / lint-imports",
        "ci / python / ruff",
        "ci / security / gitleaks",
    ]


def test_every_posting_check_in_the_graph_has_an_area() -> None:
    # A check without one has no status context to post under.
    nameless = [c.task for c in REAL_CHECKS().values() if c.check and not c.area]

    assert nameless == []


def test_check_posts_only_that_check_and_leaves_the_job_verdict(
    api: FakeGitHub, tmp_path: Path
) -> None:
    code = _post(tmp_path, "lint-node", {"ci:biome": "failure"}, "--check", "biome")

    assert code == 0, "a finished check's post does not decide the job"
    assert _states(api) == {"ci / node / biome": "failure"}
    assert not (tmp_path / "verdicts" / "lint-node.json").exists()
    assert (tmp_path / "results.posted").read_text().split() == ["biome"]


def test_the_jobs_post_skips_what_run_job_already_posted(api: FakeGitHub, tmp_path: Path) -> None:
    _post(tmp_path, "lint-node", {"ci:biome": "failure", "ci:deps": "success"}, "--check", "biome")
    api.requests.clear()

    assert _post(tmp_path, "lint-node", {"ci:biome": "failure", "ci:deps": "success"}) == 1
    assert set(_states(api)) == {"ci / node / deps", "ci / node / type-check"}
    assert _job_verdict(tmp_path, "lint-node")["status"] == "fail"


def test_a_check_post_that_did_not_land_is_posted_again_at_the_end(
    api: FakeGitHub, tmp_path: Path
) -> None:
    _post(tmp_path, "lint-node", {"ci:biome": "success"}, "--check", "biome", "--no-post")
    api.requests.clear()

    _post(tmp_path, "lint-node", {"ci:biome": "success"})
    assert "ci / node / biome" in _states(api)


def test_a_red_status_names_its_first_finding_not_just_the_log(
    api: FakeGitHub, tmp_path: Path
) -> None:
    """The verdict uploads when the job ends; the status is all a reader has before that."""
    result: nx_affected.TaskResult = {
        "status": "failure",
        "code": 1,
        "output": "tools/x.py:3:1: F401 `os` imported but unused\n",
    }
    _post(tmp_path, "lint-python", {"ci:ruff": result}, "--check", "ruff")

    description = _statuses(api)["ci / python / ruff"]["description"]
    assert description.startswith("failed — tools/x.py:3:1: F401")
    assert len(description) <= 140


def test_a_red_status_without_a_location_names_the_outputs_last_word(
    api: FakeGitHub, tmp_path: Path
) -> None:
    """Regression: an nx crash read only "failed — undefined"; its last line said SIGSEGV."""
    result: nx_affected.TaskResult = {
        "status": "failure",
        "code": 1,
        "output": "undefined\n ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL  Command was killed with SIGSEGV\n",
    }
    _post(tmp_path, "lint-python", {"ci:ruff": result}, "--check", "ruff")

    assert "SIGSEGV" in _statuses(api)["ci / python / ruff"]["description"]
