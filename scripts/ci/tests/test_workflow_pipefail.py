"""Every pipeline in a workflow or composite step runs under pipefail.

A step with no `shell:` runs as `bash -e {0}`, without pipefail, so the status
of `cmd | tail` is tail's: ci.yml's build step piped `nx run-many` into `tail`
inside a child `bash -c`, and a web build that failed on a missing env var
reported success. `shell: bash` runs `bash -eo pipefail`, but a nested
`bash -c` does not inherit the option, so it needs its own `-o pipefail`.

Neither actionlint nor shellcheck flags a missing pipefail, so this reads the
workflows directly. A step that checks PIPESTATUS itself is exempt.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import re
from typing import Any

from doc_shape import mapping
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
STEP_FILES = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")) + sorted(
    (REPO_ROOT / ".github" / "actions").glob("*/action.yml")
)

EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.S)
QUOTED = re.compile(r"'[^']*'|\"(?:\\.|[^\"\\])*\"")
COMMENT = re.compile(r"(?:^|\s)#.*$", re.M)
PIPE = re.compile(r"(?<!\|)\|(?!\|)")
SET_PIPEFAIL = re.compile(r"\bset\s+-[a-zA-Z]*o\s+pipefail\b")
NESTED_BASH = re.compile(r"\bbash((?:\s+-[a-zA-Z]+(?:\s+pipefail)?)*)\s+-c\s+'([^']*)'")


def _has_pipe(script: str) -> bool:
    """Whether the script pipes outside quotes, comments and ${{ }} expressions."""
    code = COMMENT.sub("", QUOTED.sub("''", EXPRESSION.sub("", script)))
    return bool(PIPE.search(code))


def pipefail_gaps(shell: str | None, script: str) -> list[str]:
    """List what in one step's script can lose a pipeline's exit status."""
    gaps = [
        f"nested `bash{flags} -c` pipes without -o pipefail"
        for flags, body in NESTED_BASH.findall(script)
        if _has_pipe(body) and "pipefail" not in flags and not SET_PIPEFAIL.search(body)
    ]
    if shell is not None and not shell.startswith(("bash", "sh")):
        return gaps
    covered = shell == "bash" or "pipefail" in (shell or "") or SET_PIPEFAIL.search(script)
    if not covered and "PIPESTATUS" not in script and _has_pipe(script):
        gaps.append(f"pipes under `{shell or 'bash -e {0}'}`, which has no pipefail")
    return gaps


def _steps(path: Path) -> Iterator[tuple[str, str | None, dict[str, Any]]]:
    """Every (job, effective shell, step) in a workflow or composite action."""
    doc = mapping(yaml.safe_load(path.read_text()))
    if "runs" in doc:
        for step in doc["runs"].get("steps") or []:
            yield "composite", step.get("shell"), step
        return
    workflow_shell = ((doc.get("defaults") or {}).get("run") or {}).get("shell")
    for job_name, job in (doc.get("jobs") or {}).items():
        job_shell = ((job.get("defaults") or {}).get("run") or {}).get("shell")
        for step in job.get("steps") or []:
            yield job_name, step.get("shell") or job_shell or workflow_shell, step


@pytest.mark.parametrize("path", STEP_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_step_loses_a_pipeline_exit_status(path: Path) -> None:
    failures = [
        f"{job} / {step.get('name') or step.get('id')}: {gap}"
        for job, shell, step in _steps(path)
        if "run" in step
        for gap in pipefail_gaps(shell, step["run"])
    ]
    assert not failures, (
        "Add `shell: bash` (runs `bash -eo pipefail`), `bash -o pipefail -c` for a "
        "nested shell, or drop the pipe:\n  " + "\n  ".join(failures)
    )


@pytest.mark.parametrize(
    ("shell", "script"),
    [
        (None, "nx run-many -t build 2>&1 | tail -n 60"),
        ("bash", "time bash -c 'nx run-many -t build 2>&1 | tail -n 60' | tee out"),
        ("sh", "git archive HEAD | tar -x"),
    ],
)
def test_a_pipeline_that_can_lose_its_status_is_caught(shell: str | None, script: str) -> None:
    assert pipefail_gaps(shell, script)


@pytest.mark.parametrize(
    ("shell", "script"),
    [
        ("bash", "nx run-many -t build | tail -n 60"),
        ("bash", "time bash -o pipefail -c 'nx run-many -t build | tail -n 60' | tee out"),
        (None, "set -euo pipefail\nnx run-many -t build | tail -n 60"),
        (None, 'a | tee out; [ "${PIPESTATUS[0]}" -eq 0 ]'),
        (None, "grep -qE '^(a|b)$' file || echo none  # a | b"),
        (None, "echo ${{ inputs.x || 'y' }}"),
        ("python", "print('a' | 'b')"),
    ],
)
def test_a_pipeline_that_keeps_its_status_passes(shell: str | None, script: str) -> None:
    assert not pipefail_gaps(shell, script)
