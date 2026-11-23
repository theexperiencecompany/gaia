"""Every CI step that builds the web app carries INTERNAL_API_TOKEN.

A web build prerenders against the production API. Without the token its
requests share the API's anonymous ceiling (120/min per address), and a build
makes several hundred: ts-build-test and desktop-build failed every web build
on 429 once the app-wide limiter started applying (#1853), while cf-build,
which had the token, passed. The gaia-web Docker image builds with no API URL,
so it prerenders nothing from the API and is not a step here.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from doc_shape import mapping, sequence
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"
TOKEN = "INTERNAL_API_TOKEN"
TOKEN_VALUE = "${{ secrets.INTERNAL_API_TOKEN }}"
# The job whose run-job step runs every project's nx `build` target, web:build included.
BUILD_JOB = mapping(json.loads((ROOT / "nx.json").read_text())["targetDefaults"]["build"])[
    "metadata"
]["ci"]["job"]
WEB_BUILD_COMMANDS = re.compile(
    r"cf:build|nx build web\b|nx (?:dist|pack)\b.* desktop\b"
    rf"|runner\.py run-job {re.escape(BUILD_JOB)}\b"
)


def _load(path: Path) -> dict[str, Any]:
    return mapping(yaml.safe_load(path.read_text()))


def _builds_web(run: str) -> bool:
    # A message naming the command (an echo, a comment) is not a build.
    commands = (line.strip() for line in run.splitlines())
    return any(
        WEB_BUILD_COMMANDS.search(line) for line in commands if not line.startswith(("echo", "#"))
    )


def _web_build_steps() -> list[tuple[str, dict[str, Any]]]:
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = _load(path)
        for job_name, raw in mapping(workflow["jobs"]).items():
            job = mapping(raw)
            for step in sequence(job.get("steps", [])):
                step = mapping(step)
                if _builds_web(str(step.get("run", ""))):
                    env = {
                        **mapping(workflow.get("env", {})),
                        **mapping(job.get("env", {})),
                        **mapping(step.get("env", {})),
                    }
                    found.append((f"{path.name}:{job_name}:{step.get('name', '?')}", env))
    return found


@pytest.mark.parametrize(
    ("step", "env"), _web_build_steps(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_a_web_build_step_presents_the_internal_api_token(step: str, env: dict[str, Any]) -> None:
    assert env.get(TOKEN) == TOKEN_VALUE, (
        f"{step} builds the web app against the production API without {TOKEN}: "
        f"its prerender fetches would share one runner address's anonymous rate limit"
    )


def test_the_check_finds_every_web_build() -> None:
    steps = {step for step, _ in _web_build_steps()}
    assert {
        "ci.yml:ts-build-test:Run this job's checks through nx",
        "web-build.yml:cf-build:Build Cloudflare bundle",
        "desktop-pr-build.yml:prepare:Build web (standalone)",
    } <= steps
    assert any(step.startswith("desktop-release.yml:build:") for step in steps)


def _token_reading_calls() -> list[tuple[str, dict[str, Any]]]:
    calls = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for job_name, raw in mapping(_load(path)["jobs"]).items():
            job = mapping(raw)
            uses = str(job.get("uses", ""))
            if not uses.startswith("./.github/workflows/"):
                continue
            if f"secrets.{TOKEN}" in (ROOT / uses.removeprefix("./")).read_text():
                calls.append((f"{path.name}:{job_name}", job))
    return calls


@pytest.mark.parametrize(
    ("call", "job"), _token_reading_calls(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_a_reusable_build_gets_the_token_from_its_caller(call: str, job: dict[str, Any]) -> None:
    secrets = job.get("secrets")
    assert secrets == "inherit" or mapping(secrets).get(TOKEN) == TOKEN_VALUE, (
        f"{call} calls {job['uses']}, which reads secrets.{TOKEN}, but does not pass it: "
        "a called workflow sees only the secrets its caller hands it"
    )


def test_the_caller_check_finds_the_desktop_build() -> None:
    assert "ci.yml:desktop-build" in {call for call, _ in _token_reading_calls()}
