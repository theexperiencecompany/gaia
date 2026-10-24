"""post-statuses: one commit status per check inside a grouped lane.

ci.yml folds a dozen checks into one job each (lint-node, lint-python,
lint-mixed, scan), so the checks list shows the job, not biome or mypy. Each
check's step outcome is posted back as its own `ci / <check>` status pointing at
the job, so a red biome reads as `ci / biome` on the PR. A status that says
success for a check that failed is the one outcome this must never produce, and
a status that failed to post must fail the step rather than vanish.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from github_fake import FakeGitHub, Reply
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))
import verdict

REPO = "theexperiencecompany/gaia"
SHA = "c9d667254c9d667254c9d667254c9d667254c9d6"
RUN = 4242
JOB_URL = f"https://github.com/{REPO}/actions/runs/{RUN}/job/77"
RUNNER = "gaia-home-5"


STATUSES = rf"/repos/{REPO}/statuses/{SHA}$"


def _this_job(**overrides: Any) -> dict[str, Any]:
    return {"runner_name": RUNNER, "status": "in_progress", "html_url": JOB_URL, **overrides}


@pytest.fixture(autouse=True)
def _this_run(api: FakeGitHub, monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = [_this_job(), _this_job(runner_name="gaia-home-6", html_url="elsewhere")]
    api.on("GET", r"/attempts/2/jobs$", Reply(body={"jobs": jobs}))
    api.on("POST", STATUSES, Reply(201, {}))
    monkeypatch.setenv("RUNNER_NAME", RUNNER)


def _post(*pairs: str, reused: dict[str, str] | None = None) -> int:
    argv = ["--repo", REPO, "--sha", SHA, "--run-id", str(RUN), "--run-attempt", "2"]
    if reused is not None:
        argv += ["--reused", json.dumps(reused)]
    return verdict.cmd_post_statuses([*argv, *pairs])


def _posted(api: FakeGitHub) -> list[dict[str, str]]:
    bodies: list[dict[str, str]] = []
    for req in api.requests:
        if req.method == "POST":
            assert isinstance(req.body, dict), req
            bodies.append({str(key): str(value) for key, value in req.body.items()})
    return bodies


def _statuses(api: FakeGitHub) -> dict[str, dict[str, str]]:
    return {fields["context"]: fields for fields in _posted(api)}


def test_each_check_gets_its_own_status_on_the_head_sha(api: FakeGitHub) -> None:
    assert _post("biome=success", "type-check=failure") == 0

    assert {r.path for r in api.requests if r.method == "POST"} == {f"/repos/{REPO}/statuses/{SHA}"}
    statuses = _statuses(api)
    assert sorted(statuses) == ["ci / biome", "ci / type-check"]
    assert statuses["ci / biome"]["state"] == "success"
    assert statuses["ci / type-check"]["state"] == "failure"


def test_a_failed_check_is_never_posted_as_success(api: FakeGitHub) -> None:
    _post("biome=failure", "deps=cancelled")

    states = {context: fields["state"] for context, fields in _statuses(api).items()}
    assert states == {"ci / biome": "failure", "ci / deps": "error"}


def test_every_status_links_to_the_job_that_ran_the_check(api: FakeGitHub) -> None:
    _post("biome=success")

    # This run attempt's jobs, and of those the one on THIS runner: a sibling job
    # in the same run must not be the link.
    reads = [(r.path, r.query) for r in api.requests if r.method == "GET"]
    assert reads == [(f"/repos/{REPO}/actions/runs/{RUN}/attempts/2/jobs", {"per_page": "100"})]
    assert _statuses(api)["ci / biome"]["target_url"] == JOB_URL


def test_a_skipped_check_says_whether_it_was_reused_or_had_nothing_to_check(
    api: FakeGitHub,
) -> None:
    _post("biome=skipped", "deps=skipped", reused={"biome": "passed at abc1234 in run 7"})

    statuses = _statuses(api)
    assert statuses["ci / biome"]["state"] == "success"
    assert statuses["ci / biome"]["description"].startswith("reused")
    assert "run 7" in statuses["ci / biome"]["description"]
    assert statuses["ci / deps"]["description"].startswith("skipped")


def test_an_unknown_outcome_is_an_error_not_a_pass(api: FakeGitHub) -> None:
    _post("biome=")

    assert _statuses(api)["ci / biome"]["state"] == "error"


def test_a_long_reuse_note_fits_the_status_api_limit(api: FakeGitHub) -> None:
    _post("biome=skipped", reused={"biome": "x" * 400})

    assert len(_statuses(api)["ci / biome"]["description"]) <= verdict.STATUS_DESCRIPTION_LIMIT


def test_a_post_that_keeps_failing_fails_the_step_after_trying_every_check(
    api: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    api.on("POST", STATUSES, Reply(502, {"message": "bad gateway"}))

    assert _post("biome=success", "deps=success") == 1
    # Both checks were attempted, each the client's full number of times.
    contexts = [fields["context"] for fields in _posted(api)]
    assert contexts == ["ci / biome"] * 3 + ["ci / deps"] * 3
    assert "2 status(es) never landed" in capsys.readouterr().out


def test_a_transient_post_failure_is_retried(api: FakeGitHub) -> None:
    api.on("POST", STATUSES, Reply(502, {}), Reply(201, {}))

    assert _post("biome=success") == 0
    assert [fields["context"] for fields in _posted(api)] == ["ci / biome", "ci / biome"]


def test_a_rejected_post_is_not_retried(api: FakeGitHub) -> None:
    # A 422 is the request being wrong; repeating it cannot land the status.
    api.on("POST", STATUSES, Reply(422, {"message": "Validation Failed"}))

    assert _post("biome=success") == 1
    assert len(_posted(api)) == 1


def test_no_job_on_this_runner_posts_nothing_and_fails(
    api: FakeGitHub, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RUNNER_NAME", "somewhere-else")

    assert _post("biome=success") == 1
    assert _posted(api) == []
    assert "::error::" in capsys.readouterr().out


def test_an_unreadable_jobs_listing_posts_nothing_and_fails(
    api: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    api.on("GET", r"/jobs$", Reply(503, {"message": "unavailable"}))

    assert _post("biome=success") == 1
    assert _posted(api) == []
    assert "jobs are unreadable" in capsys.readouterr().out


# --- step-outcomes: the grouped job's own verdict ---------------------------


def _outcomes(tmp_path: Path, *pairs: str, reused: dict[str, str] | None = None) -> int:
    argv = ["--lane", "lint-node", "--out", str(tmp_path), *pairs]
    if reused is not None:
        argv += ["--reused", json.dumps(reused)]
    return verdict.cmd_step_outcomes(argv)


def test_a_failed_check_fails_the_grouped_job(tmp_path: Path) -> None:
    assert _outcomes(tmp_path, "biome=success", "deps=failure") == 1
    doc = json.loads((tmp_path / "lint-node.json").read_text())
    assert doc["status"] == "fail"
    assert "deps (failure)" in doc["summary"]


def test_a_check_with_nothing_to_check_or_reused_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A TS-only PR skips every Python check by its `if:`; a reused check skips by
    # design. Neither is a failure, exactly as the gate reads a skipped job.
    code = _outcomes(
        tmp_path, "biome=skipped", "deps=success", reused={"biome": "passed at abc in run 7"}
    )

    assert code == 0
    assert "reused — passed at abc in run 7" in capsys.readouterr().out
    assert json.loads((tmp_path / "lint-node.json").read_text())["status"] == "pass"


@pytest.mark.parametrize("outcome", ["cancelled", ""])
def test_a_check_that_did_not_finish_is_not_a_pass(tmp_path: Path, outcome: str) -> None:
    assert _outcomes(tmp_path, "biome=success", f"deps={outcome}") == 1
