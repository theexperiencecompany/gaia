"""web-build.yml: one step owns removing the source maps, and it leaves the build checks theirs."""

from __future__ import annotations

from pathlib import Path
import re

from doc_shape import mapping
import yaml

ROOT = Path(__file__).resolve().parents[3]
WEB_BUILD = ROOT / ".github" / "workflows" / "web-build.yml"
NEXT_CONFIG = ROOT / "apps" / "web" / "next.config.mjs"
WORKFLOWS = ROOT / ".github" / "workflows"


def _steps() -> list[dict[str, object]]:
    job = mapping(mapping(yaml.safe_load(WEB_BUILD.read_text()))["jobs"])["cf-build"]
    return [mapping(s) for s in job["steps"]]


def test_sentry_never_deletes_the_maps_the_landing_check_reads() -> None:
    """Regression: with the token, Sentry's post-build hook deleted .next's maps and comments, and the check failed on master."""
    assert re.search(r"deleteSourcemapsAfterUpload:\s*false\b", NEXT_CONFIG.read_text())


def test_the_landing_check_runs_on_every_build_after_the_maps_leave_the_deploy() -> None:
    steps = _steps()
    names = [str(s.get("name", "")) for s in steps]
    remove = names.index("Remove source maps from the deployed bundle")
    (check,) = [i for i, s in enumerate(steps) if "verify-landing-bundle" in str(s.get("run", ""))]
    assert remove < check
    assert "if" not in steps[check], "the deploy build is checked like every other"
    assert "apps/web/.open-next" in str(steps[remove]["run"])
    assert "apps/web/.next/" not in str(steps[remove]["run"]), (
        "it would delete the maps the check reads"
    )


def test_only_a_master_build_takes_the_production_environment() -> None:
    """Regression: a dispatch on a PR branch asked for production, which refuses every branch but master."""
    job = mapping(mapping(yaml.safe_load(WEB_BUILD.read_text()))["jobs"])["cf-build"]
    assert job["environment"] == (
        "${{ (github.ref == 'refs/heads/master' && (github.event_name == 'push' || "
        "github.event_name == 'workflow_dispatch')) && 'production' || '' }}"
    )


def test_the_post_deploy_seo_run_audits_the_commit_that_was_deployed() -> None:
    # deploy-web dispatches seo-crawl.yml on master; master's tip may already carry
    # a newer squirrel baseline than the site it crawls serves.
    seo = yaml.safe_load((WORKFLOWS / "seo-crawl.yml").read_text())
    for job in ("crawl", "audit"):
        (checkout,) = [
            s for s in seo["jobs"][job]["steps"] if "actions/checkout" in s.get("uses", "")
        ]
        assert "inputs.deployed_sha" in checkout["with"]["ref"], job
    deploy = yaml.safe_load((WORKFLOWS / "deploy-web.yml").read_text())
    (dispatch,) = deploy["jobs"]["post-deploy-seo"]["steps"]
    assert '-f deployed_sha="$GITHUB_SHA"' in dispatch["run"]


def test_the_post_deploy_audit_never_queues_behind_a_crawl() -> None:
    # A run-level group made a deploy's audit wait out a 90-minute crawl, and a
    # third dispatch replaced the pending run, audit and all.
    seo = yaml.safe_load((WORKFLOWS / "seo-crawl.yml").read_text())
    assert "concurrency" not in seo
    assert "concurrency" not in seo["jobs"]["audit"]
    assert seo["jobs"]["crawl"]["concurrency"] == {
        "group": "seo-crawl",
        "cancel-in-progress": False,
    }
