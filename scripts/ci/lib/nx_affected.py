#!/usr/bin/env python3
"""Ask nx which CI tasks a change reaches, and write them as detect's outputs.

The candidates are every target of the .github/jobs projects (one project per
ci.yml job, one target per check) plus the code projects' targets a job gates
on. A task is affected when a file its inputs name changed; a job runs when a
task of its project is. Reached through `changes.sh affected`.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
JOBS_DIR = REPO_ROOT / ".github" / "jobs"
# The code projects' targets the workflows gate on: api:test opens the Python
# slices, gaia-connect:check and alert-rules:check their steps, a TypeScript
# project's build or test task puts it in ts-build-test, and docker:build is
# the image build.yml publishes.
CODE_TARGETS = ("build", "check", "docker:build", "test")
NX_JSON = REPO_ROOT / "nx.json"
TYPESCRIPT_BUILD_TARGETS = {"build", "test"}
TYPESCRIPT = "tag:scope:typescript"


@dataclass(frozen=True)
class Selection:
    tasks: dict[str, list[dict[str, str]]]

    @property
    def projects(self) -> list[str]:
        return sorted({_project(task) for task in self.tasks})


def _project(task: str) -> str:
    return task.split(":", 1)[0]


def _target(task: str) -> str:
    return task.split(":", 1)[1]


def job_targets() -> list[str]:
    targets: set[str] = set()
    for project in sorted(JOBS_DIR.glob("*/project.json")):
        targets |= set(json.loads(project.read_text())["targets"])
    return sorted(targets)


def _nx(*args: str) -> str:
    return subprocess.run(
        ["pnpm", "exec", "nx", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "NX_NO_CLOUD": "true", "NX_DAEMON": "false"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _json_after_banner(out: str, opener: str) -> object:
    """Parse nx's JSON, which a plugin's deprecation notice may precede on stdout."""
    return json.loads(out[out.index(opener) :])


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [f for f in out.splitlines() if (REPO_ROOT / f).is_file()]


def select(range_args: list[str]) -> Selection:
    out = _nx("affected", "-t", *job_targets(), *CODE_TARGETS, "--explain=stdout", *range_args)
    explained = _json_after_banner(out, "{")
    assert isinstance(explained, dict)
    return Selection(tasks=explained["affected"])


def typescript_projects(selection: Selection) -> str:
    tagged = _json_after_banner(_nx("show", "projects", "--projects", TYPESCRIPT, "--json"), "[")
    assert isinstance(tagged, list)
    built = {
        _project(task) for task in selection.tasks if _target(task) in TYPESCRIPT_BUILD_TARGETS
    }
    return ",".join(sorted(built.intersection(tagged)))


def release_groups(selection: Selection) -> list[str]:
    """Name the nx.json release groups with an affected image, the images build.yml publishes."""
    groups = json.loads(NX_JSON.read_text())["release"]["groups"]
    built = {_project(task) for task in selection.tasks if _target(task) == "docker:build"}
    return sorted(name for name, group in groups.items() if built.intersection(group["projects"]))


def _first_reason(reasons: list[dict[str, str]]) -> str:
    first = reasons[0]
    more = f" (+{len(reasons) - 1} more)" if len(reasons) > 1 else ""
    return f"{first.get('file') or first['kind']}{more}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all", action="store_true", help="every task, as on a dispatch")
    scope.add_argument("--base", help="the revision the change is measured from")
    parser.add_argument("--head", default="HEAD")
    opts = parser.parse_args()

    range_args = (
        # One argument per file: Linux caps a single argv entry at 128 KiB.
        ["--files", *tracked_files()]
        if opts.all
        else [f"--base={opts.base}", f"--head={opts.head}"]
    )
    selection = select(range_args)
    outputs = {
        "tasks": json.dumps(sorted(selection.tasks)),
        "projects": json.dumps(selection.projects),
        "typescript_projects": typescript_projects(selection),
        "release_groups": json.dumps(release_groups(selection)),
    }
    lines = "".join(f"{key}={value}\n" for key, value in outputs.items())
    sink = os.environ.get("GITHUB_OUTPUT")
    if sink:
        with open(sink, "a", encoding="utf-8") as out:
            out.write(lines)
    else:
        sys.stdout.write(lines)

    print(
        f"::group::{len(selection.tasks)} affected task(s), each with the first file that reached it"
    )
    for task, reasons in sorted(selection.tasks.items()):
        print(f"{task} <- {_first_reason(reasons)}")
    print("::endgroup::")
    jobs = ", ".join(selection.projects) or "none"
    print(f"affected: {len(selection.tasks)} task(s); projects with work: {jobs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
