"""The home box is identified by its runner name, never by the runner kind.

Blacksmith overflow runners report `runner.environment == 'self-hosted'` just
like the box, so every lane that keyed a box-only assumption on it (the
setup.sh-installed trivy, the `gaia-ci` buildx builder, the persistent
workspace and caches) broke there: `scan` failed 4/4 with `trivy: command not
found` and `docker-image` with "gaia-ci builder missing". The box's runners
are named `gaia-home-<n>` by gaia-infra's setup.sh, so that prefix is the one
signal; this test fails on any code under .github/ or scripts/ci that reads
the runner kind instead, and on a prefix that drifts between the three places
that spell it.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_CI = REPO_ROOT / "scripts" / "ci"
RUNNER_HOST_SH = SCRIPTS_CI / "lib" / "runner-host.sh"
CODE_SUFFIXES = {".yml", ".yaml", ".sh", ".py", ".mjs"}
RUNNER_KIND = re.compile(r"runner\.environment|RUNNER_ENVIRONMENT")
BOX_EXPRESSION = re.compile(r"startsWith\(runner\.name, '([^']*)'\)")


def _code_files() -> list[Path]:
    roots = [REPO_ROOT / ".github", SCRIPTS_CI]
    return sorted(
        path
        for root in roots
        for path in root.rglob("*")
        if path.suffix in CODE_SUFFIXES and (SCRIPTS_CI / "tests") not in path.parents
    )


def _box_prefix_from_shell() -> str:
    proc = subprocess.run(
        ["bash", "-c", 'source "$1"; printf %s "$GAIA_BOX_RUNNER_PREFIX"', "x", RUNNER_HOST_SH],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


def test_no_ci_code_reads_the_runner_kind() -> None:
    hits = [
        f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}"
        for path in _code_files()
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if RUNNER_KIND.search(line)
    ]
    assert not hits, (
        "runner.environment / RUNNER_ENVIRONMENT is 'self-hosted' on Blacksmith too. "
        "Ask whether this is the box with startsWith(runner.name, 'gaia-home-') in an "
        "expression, or ci_on_the_box (scripts/ci/lib/runner-host.sh) in shell:\n" + "\n".join(hits)
    )


def test_every_box_expression_uses_the_canonical_prefix() -> None:
    prefix = _box_prefix_from_shell()
    prefixes = {
        match for path in _code_files() for match in BOX_EXPRESSION.findall(path.read_text())
    }
    assert prefixes == {prefix}


@pytest.mark.parametrize(
    ("runner_name", "on_the_box"),
    [("gaia-home-3", True), ("blacksmith-4vcpu-ubuntu-2404-abc", False), ("", False)],
)
def test_ci_on_the_box_reads_the_runner_name(runner_name: str, on_the_box: bool) -> None:
    proc = subprocess.run(
        ["bash", "-c", 'source "$1"; ci_on_the_box', "x", RUNNER_HOST_SH],
        env={"PATH": "/usr/bin:/bin", "RUNNER_NAME": runner_name},
        check=False,
    )
    assert (proc.returncode == 0) is on_the_box


def test_runner_py_names_the_same_box_prefix_as_the_shell() -> None:
    runner = (SCRIPTS_CI / "runner.py").read_text()
    assert re.search(
        rf'^BOX_RUNNER_NAME_PREFIX = "{re.escape(_box_prefix_from_shell())}"$', runner, re.MULTILINE
    )


def test_every_home_label_is_runner_pys() -> None:
    """ci-health and the selector name the box's runner label too; a renamed label left them watching nothing."""
    (label,) = re.findall(
        r'^DEFAULT_HOME_LABEL = "([^"]+)"$', (SCRIPTS_CI / "runner.py").read_text(), re.MULTILINE
    )
    health = yaml.safe_load((REPO_ROOT / ".github/workflows/ci-health.yml").read_text())
    expected = [
        s["env"]["EXPECTED"]
        for job in health["jobs"].values()
        for s in job["steps"]
        if "EXPECTED" in s.get("env", {})
    ]
    assert expected == [label]
    selector = yaml.safe_load((REPO_ROOT / ".github/actions/select-runner/action.yml").read_text())
    defaults = {
        name: spec.get("default") for name, spec in selector["inputs"].items() if "label" in name
    }
    assert set(filter(None, defaults.values())) <= {label}, defaults
