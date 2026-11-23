"""deploy.sh smoke: the anonymous post-deploy read of production, against local stub servers.

Nothing outside-in checked prod after a deploy: on 2026-11-23 a release made the anonymous
rate limit apply, the deploy went green, and an hour later every web build failed on 429s.
These drive the real script and the real targets file over real HTTP; only prod is a stub.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess

from http_stub import Response, Routes, serve
from lib import prod_smoke
import yaml

CI = Path(__file__).parent.parent
SCRIPT = CI / "deploy.sh"
WORKFLOW = CI.parent.parent / ".github/workflows/deploy-swarm-prod.yml"

# The paths come from the real targets file, so a renamed target cannot leave a stub behind.
TARGETS = {target.name: target for target in prod_smoke.load_targets(prod_smoke.TARGETS_FILE)}
COMMUNITY = TARGETS["integrations-community"].path
CONFIG = TARGETS["integrations-config"].path
PLANS = TARGETS["plans"].path
EXPLORE = TARGETS["workflows-explore"].path
BURST_PATHS = tuple(target.path for target in TARGETS.values() if target.burst)
LIMIT = "120 per 1 minute"


def detail(slug: str) -> str:
    return TARGETS["integration-detail"].path.replace("{slug}", slug)


def ok_json(document: object) -> Response:
    return (200, {"Content-Type": "application/json"}, json.dumps(document))


def ok_html(title: str) -> Response:
    return (200, {"Content-Type": "text/html"}, f"<html><head><title>{title}</title></head></html>")


def refused(retry_after: int = 1) -> Response:
    return (
        429,
        {"Retry-After": str(retry_after)},
        json.dumps({"message": LIMIT, "code": "rate_limit_exceeded"}),
    )


def healthy_api() -> Routes:
    return {
        "/health": ok_json({"status": "online", "commit": "76ec6cc4", "version": "0.25.0"}),
        COMMUNITY: ok_json({"integrations": [{"slug": "postman_full"}], "total": 1}),
        CONFIG: ok_json({"integrations": [{"slug": "googlecalendar"}]}),
        detail("postman_full"): ok_json({"slug": "postman_full", "name": "Postman"}),
        detail("googlecalendar"): ok_json({"slug": "googlecalendar", "name": "Calendar"}),
        PLANS: ok_json([{"id": "pro"}]),
        EXPLORE: ok_json({"workflows": []}),
    }


def healthy_web() -> Routes:
    return {
        "/": ok_html("GAIA AI: The Personal Assistant"),
        "/marketplace": ok_html("AI Integration Marketplace: Connect Your Tools"),
        "/marketplace/postman-full": ok_html("Postman MCP Server | GAIA"),
        "/marketplace/googlecalendar": ok_html("Google Calendar AI | GAIA"),
    }


@dataclass
class Run:
    proc: subprocess.CompletedProcess[str]
    outputs: dict[str, str]
    api_gets: list[str]
    web_gets: list[str]

    @property
    def verdict(self) -> str | None:
        return self.outputs.get("verdict")


def smoke(
    tmp_path: Path,
    api: Routes | None = None,
    web: Routes | None = None,
    *extra: str,
    api_url: str | None = None,
    web_url: str | None = None,
) -> Run:
    """Run deploy.sh smoke against stub origins with no retry delay; return its outputs and every GET."""
    api_gets: list[str] = []
    web_gets: list[str] = []
    output = tmp_path / "github_output"
    output.write_text("")
    with ExitStack() as stack:
        api_base = api_url or stack.enter_context(serve(api or healthy_api(), gets=api_gets))
        web_base = web_url or stack.enter_context(serve(web or healthy_web(), gets=web_gets))
        proc = subprocess.run(
            ["bash", str(SCRIPT), "smoke", "--retry-delay", "0", "--timeout", "5", *extra],
            env={
                "PATH": os.environ["PATH"],
                "PROD_ORIGIN": api_base,
                "PROD_WEB_ORIGIN": web_base,
                "GITHUB_OUTPUT": str(output),
                "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
            },
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line)
    return Run(proc, outputs, api_gets, web_gets)


def test_a_healthy_prod_passes_and_stays_far_under_the_anonymous_ceiling(tmp_path: Path) -> None:
    run = smoke(tmp_path)

    assert run.proc.returncode == 0, run.proc.stdout + run.proc.stderr
    assert run.verdict == "pass"
    burst = [path for path in run.api_gets if path in BURST_PATHS]
    # Four single reads of the burst targets, then the burst: 120 // 4 = 30 reads.
    assert len(burst) == 4 + 30
    assert len(run.api_gets) <= 120 // 2
    assert "deploy smoke: OK" in run.proc.stdout


def test_a_public_read_failing_on_every_attempt_fails_with_url_status_and_body(
    tmp_path: Path,
) -> None:
    api = healthy_api() | {CONFIG: (503, {}, "upstream connect error")}

    run = smoke(tmp_path, api)

    assert run.proc.returncode != 0
    assert run.verdict == "fail"
    url = f"{run.outputs['summary'].split('(', 1)[1].split(')', 1)[0]}"
    assert url.startswith("http://127.0.0.1:") and url.endswith(CONFIG)
    assert run.outputs["summary"].startswith("integrations-config: 503 on 3/3 attempts")
    assert "first bytes: upstream connect error" in run.proc.stderr
    assert "it was not rolled back" in run.proc.stdout


def test_a_read_that_recovers_on_retry_only_warns(tmp_path: Path) -> None:
    api = healthy_api() | {
        CONFIG: [(502, {}, "bad gateway"), ok_json({"integrations": [{"slug": "x"}]})]
    }

    run = smoke(tmp_path, api)

    assert run.proc.returncode == 0, run.proc.stderr
    assert run.verdict == "warn"
    assert "integrations-config: passed on attempt 2 after 502" in run.outputs["summary"]


def test_a_429_on_a_public_read_is_a_hard_failure_naming_the_limit(tmp_path: Path) -> None:
    api = healthy_api() | {PLANS: refused(retry_after=0)}

    run = smoke(tmp_path, api)

    assert run.verdict == "fail"
    assert f"plans: 429 rate limited ({LIMIT}) on 3/3 attempts" in run.proc.stderr


def test_a_public_read_that_now_wants_auth_fails(tmp_path: Path) -> None:
    api = healthy_api() | {EXPLORE: (401, {}, json.dumps({"message": "Not authenticated"}))}

    run = smoke(tmp_path, api)

    assert run.verdict == "fail"
    assert "workflows-explore: 401 on 3/3 attempts" in run.proc.stderr


def test_a_200_that_is_not_the_real_read_fails_on_content(tmp_path: Path) -> None:
    api = healthy_api() | {
        "/health": ok_json({"status": "degraded", "commit": "x", "version": "1"})
    }

    run = smoke(tmp_path, api)

    assert run.verdict == "fail"
    assert (
        "api-health: JSON status='degraded', expected 'online' on 3/3 attempts" in run.proc.stderr
    )


def test_an_html_error_page_where_json_belongs_fails(tmp_path: Path) -> None:
    api = healthy_api() | {COMMUNITY: (200, {}, "<html>502 Bad Gateway</html>")}

    run = smoke(tmp_path, api)

    assert run.verdict == "fail"
    assert "integrations-community: body is not JSON on 3/3 attempts" in run.proc.stderr


def test_the_detail_slug_is_the_first_one_the_list_read_returned(tmp_path: Path) -> None:
    run = smoke(tmp_path)

    assert "/api/v1/integrations/public/postman_full" in run.api_gets
    # The web app spells the same slug with hyphens (marketplaceSlug).
    assert "/marketplace/postman-full" in run.web_gets


def test_an_empty_community_list_takes_the_slug_from_the_native_config(tmp_path: Path) -> None:
    api = healthy_api() | {COMMUNITY: ok_json({"integrations": [], "total": 0})}

    run = smoke(tmp_path, api)

    assert run.verdict == "pass", run.proc.stderr
    assert "/api/v1/integrations/public/googlecalendar" in run.api_gets
    assert "/marketplace/googlecalendar" in run.web_gets


def test_a_broken_page_warns_but_never_rolls_the_backend_back(tmp_path: Path) -> None:
    web = healthy_web() | {"/": (500, {}, '<html><div id="__next_error__"></div></html>')}

    run = smoke(tmp_path, web=web)

    assert run.proc.returncode == 0, run.proc.stderr
    assert run.verdict == "warn"
    assert "::warning::smoke: home: 500 on 3/3 attempts" in run.proc.stderr


def test_a_page_that_redirects_is_not_counted_as_rendered(tmp_path: Path) -> None:
    web = healthy_web() | {"/marketplace": (307, {"Location": "/login"}, "")}

    run = smoke(tmp_path, web=web)

    assert run.verdict == "warn"
    assert "marketplace: 307 -> /login on 3/3 attempts" in run.proc.stderr


def test_the_next_error_page_served_as_200_is_caught(tmp_path: Path) -> None:
    web = healthy_web() | {
        "/marketplace": ok_html('AI Integration Marketplace</title><div id="__next_error__">')
    }

    run = smoke(tmp_path, web=web)

    assert "marketplace: rendered the Next error page" in run.proc.stderr


def test_a_burst_refused_only_in_an_already_hot_window_warns(tmp_path: Path) -> None:
    # The single read, five burst reads, a 429, then a fresh window that takes them all.
    plans = [ok_json([{"id": "pro"}])] * 4 + [refused(retry_after=1)] + [ok_json([{"id": "pro"}])]
    api = healthy_api() | {PLANS: plans}

    run = smoke(tmp_path, api)

    assert run.proc.returncode == 0, run.proc.stderr
    assert run.verdict == "warn"
    assert f"this address was already rate limited ({LIMIT})" in run.proc.stderr


def test_a_burst_refused_again_in_a_fresh_window_fails(tmp_path: Path) -> None:
    plans = [ok_json([{"id": "pro"}])] * 4 + [refused(retry_after=1)]
    api = healthy_api() | {PLANS: plans}

    run = smoke(tmp_path, api)

    assert run.verdict == "fail"
    assert "burst: 429 after 2 anonymous reads in a fresh window, under the 30" in run.proc.stderr
    assert LIMIT in run.outputs["summary"]


def test_a_read_that_breaks_during_the_burst_and_stays_broken_fails(tmp_path: Path) -> None:
    api = healthy_api() | {PLANS: [ok_json([{"id": "pro"}]), (503, {}, "upstream connect error")]}

    run = smoke(tmp_path, api)

    assert run.verdict == "fail"
    assert "plans: 503 on 3/3 attempts" in run.proc.stderr


def test_a_read_that_breaks_once_during_the_burst_and_recovers_warns(tmp_path: Path) -> None:
    plans = [
        ok_json([{"id": "pro"}]),
        (503, {}, "upstream connect error"),
        ok_json([{"id": "pro"}]),
    ]
    api = healthy_api() | {PLANS: plans}

    run = smoke(tmp_path, api)

    assert run.proc.returncode == 0, run.proc.stderr
    assert run.verdict == "warn"
    assert "::warning::smoke: burst: plans: 503" in run.proc.stderr


def test_the_burst_is_a_quarter_of_the_anonymous_ceiling(tmp_path: Path) -> None:
    limits = tmp_path / "request_limits.py"
    limits.write_text("SIGNED_IN_USER_PER_MINUTE = 300\nANONYMOUS_VIEWER_PER_MINUTE = 40\n")

    run = smoke(tmp_path, None, None, "--limits-file", str(limits))

    assert len([path for path in run.api_gets if path in BURST_PATHS]) == 4 + 10


def test_prod_unreachable_from_the_runner_is_undecided_not_a_failure(tmp_path: Path) -> None:
    closed = "http://127.0.0.1:9"

    run = smoke(tmp_path, api_url=closed, web_url=closed)

    assert run.proc.returncode != 0
    assert run.verdict == "error"
    assert "prod is unjudged" in run.proc.stdout


def test_a_smoke_that_crashes_writes_no_verdict(tmp_path: Path) -> None:
    targets = tmp_path / "targets.toml"
    targets.write_text(
        'targets = [{ name = "x", base = "api", path = "/", gate = "fail", typo = 1 }]\n'
    )

    run = smoke(tmp_path, None, None, "--targets", str(targets))

    assert run.proc.returncode != 0
    assert "verdict" not in run.outputs
    assert "unknown keys ['typo']" in run.proc.stderr


def _deploy_steps() -> list[dict[str, object]]:
    document = yaml.safe_load(WORKFLOW.read_text())
    steps: list[dict[str, object]] = document["jobs"]["deploy"]["steps"]
    return steps


def _index(steps: list[dict[str, object]], predicate: str) -> int:
    return next(
        i
        for i, step in enumerate(steps)
        if step.get("id") == predicate or step.get("run") == predicate
    )


def test_latest_moves_once_prod_serves_the_release_whatever_the_smoke_says() -> None:
    """Regression: :latest moved only after a passing smoke, so a failed one left it behind prod.

    Nothing rolls a failed smoke back, so the release serves either way, and the next deploy
    whose tag is empty resolves :latest: an old :latest rolls the old image onto new data.
    """
    steps = _deploy_steps()
    retag = _index(steps, "bash scripts/ci/deploy.sh retag from-env")
    smoke = _index(steps, "smoke")

    assert _index(steps, "verify") < retag < smoke
    assert "smoke" not in str(steps[retag]["if"])
    assert steps[smoke]["run"] == "bash scripts/ci/deploy.sh smoke"
    assert "continue-on-error" not in steps[smoke]


def test_the_advertised_smoke_command_runs_in_a_plain_shell() -> None:
    document = yaml.safe_load(WORKFLOW.read_text())
    origins = {key: document["env"][key] for key in ("PROD_ORIGIN", "PROD_WEB_ORIGIN")}
    advertised = [
        str(step["env"]["ACTION"])
        for step in _deploy_steps()
        if "deploy.sh smoke" in str(step.get("env", {}).get("ACTION", ""))
    ]

    assert advertised
    for action in advertised:
        for key, origin in origins.items():
            assert f"{key}={origin}" in action


def test_a_failed_smoke_alerts_once_and_changes_nothing_in_production() -> None:
    document = yaml.safe_load(WORKFLOW.read_text())
    steps = document["jobs"]["deploy"]["steps"]
    alerts = [s for s in steps if "steps.smoke.outputs.verdict == 'fail'" in str(s.get("if", ""))]

    assert len(alerts) == 1
    assert "NOT rolled back" in alerts[0]["env"]["IMPACT"]
    assert "action=rollback" in alerts[0]["env"]["ACTION"]
    # The rollback job stays the operator's: dispatch only, never fed by the deploy job.
    rollback = document["jobs"]["rollback"]
    assert "needs" not in rollback
    assert (
        rollback["if"] == "github.event_name == 'workflow_dispatch' && inputs.action == 'rollback'"
    )
    assert "outputs" not in document["jobs"]["deploy"]
