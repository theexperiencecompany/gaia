"""web-build.yml: one step owns removing the source maps, and it leaves the build checks theirs."""

from __future__ import annotations

from pathlib import Path
import re

from doc_shape import mapping
import yaml

ROOT = Path(__file__).resolve().parents[3]
WEB_BUILD = ROOT / ".github" / "workflows" / "web-build.yml"
NEXT_CONFIG = ROOT / "apps" / "web" / "next.config.mjs"


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
