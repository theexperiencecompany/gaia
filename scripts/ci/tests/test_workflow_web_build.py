"""web-build.yml: the checks that read the build's source maps run only on a build that keeps them."""

from __future__ import annotations

from pathlib import Path

from doc_shape import mapping
import yaml

WEB_BUILD = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "web-build.yml"


def test_the_landing_bundle_check_never_runs_on_the_build_that_uploads_its_maps() -> None:
    """Regression: master's deploy build uploads its source maps to Sentry, which strips them, and the check failed on it."""
    job = mapping(mapping(yaml.safe_load(WEB_BUILD.read_text()))["jobs"])["cf-build"]
    steps = [mapping(s) for s in job["steps"]]
    (build,) = [s for s in steps if s.get("name") == "Build Cloudflare bundle"]
    assert "SENTRY_AUTH_TOKEN" in mapping(build["env"]), "the token this test guards against moved"
    (check,) = [s for s in steps if "verify-landing-bundle" in str(s.get("run", ""))]
    condition = str(check.get("if", ""))
    assert "github.event_name == 'pull_request'" in condition
    assert "github.event_name == 'merge_group'" in condition
    assert "push" not in condition and "workflow_dispatch" not in condition
