#!/usr/bin/env python3
"""Tool-version skew guard: pre-commit hooks and CI must run the SAME pins.

The whole point of pinning is that "passed locally" means "passes CI". This
check fails when the versions drift apart:

  - apps/api/.pre-commit-config.yaml must invoke exactly these pinned tools:
      ruff@0.14.13, mypy@1.19.1, bandit@1.9.4, pip-audit@2.10.1
  - code-quality.yml must scan with ruff@0.14.13 (the ruff lane)
  - main.yml's diff-cover gate must use diff-cover==10.5.1
  - code-quality.yml's interrogate/xenon lanes must use interrogate==1.7.0 /
    xenon==0.9.3

Single source of truth is the EXPECTED table below; bump it in the same commit
that bumps any invocation, or this fails and tells you which side drifted.

Usage::

    python3 tools/lints/check_tool_pins.py

Stdlib only.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

from _common import Violation, report_rule

RULE = "tool-pins"
WHY = (
    "local hooks and CI must run the same tool versions \u2014 version skew makes "
    "'passed locally' and 'passed CI' different statements"
)
DOC = "tools/lints/README.md#tool-pins"

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parents[1]

PRE_COMMIT = REPO_ROOT / "apps/api/.pre-commit-config.yaml"
CODE_QUALITY = REPO_ROOT / ".github/workflows/code-quality.yml"
MAIN = REPO_ROOT / ".github/workflows/main.yml"

#: tool -> exact version every surface must agree on.
EXPECTED = {
    "ruff": "0.14.13",
    "mypy": "1.19.1",
    "bandit": "1.9.4",
    "pip-audit": "2.10.1",
    "diff-cover": "10.5.1",
    "interrogate": "1.7.0",
    "xenon": "0.9.3",
}

# Where each expectation must literally appear. Values are the module
# constants naming the surface files, resolved at call time (not import time)
# so the guard always reads the constants it reports against — and so the
# tests can monkeypatch them onto fixture files.
SURFACES = {
    "ruff": ("PRE_COMMIT", "CODE_QUALITY"),
    "mypy": ("PRE_COMMIT",),
    "bandit": ("PRE_COMMIT",),
    "pip-audit": ("PRE_COMMIT",),
    "diff-cover": ("MAIN",),
    "interrogate": ("CODE_QUALITY",),
    "xenon": ("CODE_QUALITY",),
}


def _surface_files(tool: str) -> list[Path]:
    """The surfaces a tool's pin must appear on, from the current constants."""
    return [globals()[name] for name in SURFACES[tool]]


def _executable_text(text: str) -> str:
    """The file text with comments removed — prose cannot pin a tool.

    Full-line comments are dropped, and each remaining line is cut at its
    first ``#`` (a trailing comment). What is left is only executable/config
    context: the literal lines a pin must be part of. A mention that lives in
    a comment — full-line or trailing — is not a pin and must never satisfy
    the guard.
    """
    lines = [
        line.split("#", 1)[0] for line in text.splitlines() if not line.lstrip().startswith("#")
    ]
    return "\n".join(lines)


def _missing(tool: str, version: str) -> list[Path]:
    """Surfaces missing an explicit pin of tool@version / tool==version."""
    out: list[Path] = []
    for surface in _surface_files(tool):
        text = _executable_text(surface.read_text(encoding="utf-8"))
        if tool == "ruff":
            # pre-commit expresses this as a rev under the ruff-pre-commit repo
            pat = re.compile(rf"ruff-pre-commit\n\s*rev:\s*v{re.escape(version)}")
            if pat.search(text):
                continue
        if f"{tool}@{version}" in text or f"{tool}=={version}" in text:
            continue
        out.append(surface)
    return out


def main(argv: list[str]) -> int:
    del argv
    violations: list[Violation] = []
    for tool, version in sorted(EXPECTED.items()):
        for surface in _missing(tool, version):
            violations.append(
                Violation(
                    path=surface,
                    line=1,
                    detail=f"{tool} is not pinned to {version} in {surface.name}",
                    fix=(
                        f"pin it ({tool}@{version} for uvx invocations, "
                        f"{tool}=={version} for uv-tool-run) — or bump EXPECTED "
                        f"in tools/lints/check_tool_pins.py in the same commit"
                    ),
                )
            )

    if violations:
        report_rule(RULE, WHY, DOC, violations)
        print(f"\n{len(violations)} unpinned tool invocation(s).", file=sys.stderr)
        return 1

    print(f"{RULE}: OK — {len(EXPECTED)} tool pins consistent across hooks and CI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
