"""post-statuses: one commit status per check inside a grouped lane.

ci.yml folds a dozen checks into one job each (lint-node, lint-python,
lint-mixed, scan), so the checks list shows the job, not biome or mypy. Each
check's step outcome is posted back as its own `ci / <check>` status pointing at
the job, so a red biome reads as `ci / biome` on the PR. A status that says
success for a check that failed is the one outcome this must never produce, and
a status that failed to post must fail the step rather than vanish.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "verdict", REPO_ROOT / "scripts" / "ci" / "verdict.py"
)
assert _SPEC is not None and _SPEC.loader is not None
verdict = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verdict)

REPO = "theexperiencecompany/gaia"
SHA = "c9d667254c9d667254c9d667254c9d667254c9d6"
RUN = 4242
JOB_URL = f"https://github.com/{REPO}/actions/runs/{RUN}/job/77"
RUNNER = "gaia-home-5"


class _Api:
    """Stands in for `gh api`: one jobs listing, and a record of every status posted."""

    def __init__(self, jobs: list[dict[str, Any]], *, failing: int = 0) -> None:
        self.jobs = jobs
        self.failing = failing
        self.asked: list[str] = []
        self.posted: list[tuple[str, dict[str, str]]] = []

    def read(self, endpoint: str) -> dict[str, Any] | None:
        self.asked.append(endpoint)
        return {"jobs": self.jobs}

    def post(self, endpoint: str, fields: dict[str, str]) -> bool:
        self.posted.append((endpoint, fields))
        if self.failing:
            self.failing -= 1
            return False
        return True


def _this_job(**overrides: Any) -> dict[str, Any]:
    return {"runner_name": RUNNER, "status": "in_progress", "html_url": JOB_URL, **overrides}


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> _Api:
    stub = _Api([_this_job(), _this_job(runner_name="gaia-home-6", html_url="elsewhere")])
    monkeypatch.setattr(verdict, "_gh_json", stub.read)
    monkeypatch.setattr(verdict, "_gh_post", stub.post)
    monkeypatch.setattr(verdict.time, "sleep", lambda seconds: None)
    monkeypatch.setenv("RUNNER_NAME", RUNNER)
    return stub


def _post(*pairs: str, reused: dict[str, str] | None = None) -> int:
    argv = ["--repo", REPO, "--sha", SHA, "--run-id", str(RUN), "--run-attempt", "2"]
    if reused is not None:
        argv += ["--reused", json.dumps(reused)]
    return verdict.cmd_post_statuses([*argv, *pairs])


def _statuses(api: _Api) -> dict[str, dict[str, str]]:
    return {fields["context"]: fields for _, fields in api.posted}


def test_each_check_gets_its_own_status_on_the_head_sha(api: _Api) -> None:
    assert _post("biome=success", "type-check=failure") == 0

    assert {endpoint for endpoint, _ in api.posted} == {f"repos/{REPO}/statuses/{SHA}"}
    statuses = _statuses(api)
    assert sorted(statuses) == ["ci / biome", "ci / type-check"]
    assert statuses["ci / biome"]["state"] == "success"
    assert statuses["ci / type-check"]["state"] == "failure"


def test_a_failed_check_is_never_posted_as_success(api: _Api) -> None:
    _post("biome=failure", "deps=cancelled")

    states = {context: fields["state"] for context, fields in _statuses(api).items()}
    assert states == {"ci / biome": "failure", "ci / deps": "error"}


def test_every_status_links_to_the_job_that_ran_the_check(api: _Api) -> None:
    _post("biome=success")

    # This run attempt's jobs, and of those the one on THIS runner: a sibling job
    # in the same run must not be the link.
    assert api.asked == [f"repos/{REPO}/actions/runs/{RUN}/attempts/2/jobs?per_page=100"]
    assert _statuses(api)["ci / biome"]["target_url"] == JOB_URL


def test_a_skipped_check_says_whether_it_was_reused_or_had_nothing_to_check(api: _Api) -> None:
    _post("biome=skipped", "deps=skipped", reused={"biome": "passed at abc1234 in run 7"})

    statuses = _statuses(api)
    assert statuses["ci / biome"]["state"] == "success"
    assert statuses["ci / biome"]["description"].startswith("reused")
    assert "run 7" in statuses["ci / biome"]["description"]
    assert statuses["ci / deps"]["description"].startswith("skipped")


def test_an_unknown_outcome_is_an_error_not_a_pass(api: _Api) -> None:
    _post("biome=")

    assert _statuses(api)["ci / biome"]["state"] == "error"


def test_a_long_reuse_note_fits_the_status_api_limit(api: _Api) -> None:
    _post("biome=skipped", reused={"biome": "x" * 400})

    assert len(_statuses(api)["ci / biome"]["description"]) <= verdict.STATUS_DESCRIPTION_LIMIT


def test_a_post_that_keeps_failing_fails_the_step_after_trying_every_check(api: _Api) -> None:
    api.failing = 99

    assert _post("biome=success", "deps=success") == 1
    # Both checks were attempted, each the full number of times.
    contexts = [fields["context"] for _, fields in api.posted]
    assert contexts.count("ci / biome") == verdict.STATUS_POST_ATTEMPTS
    assert contexts.count("ci / deps") == verdict.STATUS_POST_ATTEMPTS


def test_a_transient_post_failure_is_retried(api: _Api) -> None:
    api.failing = 1

    assert _post("biome=success") == 0
    assert [fields["context"] for _, fields in api.posted] == ["ci / biome", "ci / biome"]


def test_no_job_on_this_runner_posts_nothing_and_fails(
    api: _Api, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RUNNER_NAME", "somewhere-else")

    assert _post("biome=success") == 1
    assert api.posted == []
    assert "::error::" in capsys.readouterr().out


def test_an_unreadable_jobs_listing_posts_nothing_and_fails(
    api: _Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verdict, "_gh_json", lambda endpoint: None)

    assert _post("biome=success") == 1
    assert api.posted == []


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
