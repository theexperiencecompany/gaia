#!/usr/bin/env python3
"""Tool-version skew guard: every surface that runs a linter runs the SAME pin.

The whole point of pinning is that "passed locally" means "passes CI". This
check fails when the versions drift apart across the surfaces in SURFACES:
both pre-commit configs, code-quality.yml, the local lane table
(scripts/dev/verify-lanes.json), the root package.json quality scripts, the
api mise tasks and taskipy scripts, the ignore-staleness guard's own ruff
invocation, uv.lock, and for biome pnpm-lock.yaml plus every biome.json schema.

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
ROOT_PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"
CODE_QUALITY = REPO_ROOT / ".github/workflows/code-quality.yml"
VERIFY_LANES = REPO_ROOT / "scripts/dev/verify-lanes.json"
ROOT_PACKAGE_JSON = REPO_ROOT / "package.json"
API_MISE = REPO_ROOT / "apps/api/mise.toml"
API_PYPROJECT = REPO_ROOT / "apps/api/pyproject.toml"
PNPM_LOCK = REPO_ROOT / "pnpm-lock.yaml"
IGNORE_STALENESS = REPO_ROOT / "tools/lints/check_ignore_staleness.py"
UV_LOCK = REPO_ROOT / "uv.lock"
BIOME_CONFIGS = (
    REPO_ROOT / "biome.json",
    REPO_ROOT / "apps/desktop/biome.json",
    REPO_ROOT / "apps/mobile/biome.json",
)

#: tool -> exact version every surface must agree on.
EXPECTED = {
    "ruff": "0.14.13",
    "mypy": "1.19.1",
    "bandit": "1.9.4",
    "pip-audit": "2.10.1",
    "interrogate": "1.7.0",
    "xenon": "0.9.3",
    "biome": "2.5.7",
}

# Where each expectation must literally appear. Values are the module
# constants naming the surface files (a Path, or a tuple of Paths), resolved
# at call time (not import time) so the guard always reads the constants it
# reports against — and so the tests can monkeypatch them onto fixture files.
SURFACES = {
    # `uv run ruff` surfaces (nx targets, the Claude hook, package.json) are
    # pinned by uv.lock; the uvx ones name the version themselves.
    "ruff": ("PRE_COMMIT", "ROOT_PRE_COMMIT", "CODE_QUALITY", "IGNORE_STALENESS", "UV_LOCK"),
    # The api mypy hook runs `uv run mypy`, so the lockfile IS the pin.
    "mypy": ("UV_LOCK",),
    "bandit": ("PRE_COMMIT", "CODE_QUALITY", "VERIFY_LANES", "API_MISE", "API_PYPROJECT"),
    "pip-audit": ("PRE_COMMIT", "CODE_QUALITY", "VERIFY_LANES", "API_MISE", "API_PYPROJECT"),
    "interrogate": ("CODE_QUALITY", "VERIFY_LANES", "ROOT_PACKAGE_JSON"),
    "xenon": ("CODE_QUALITY", "VERIFY_LANES", "ROOT_PACKAGE_JSON"),
    # package.json keeps syncpack's caret policy; the version pnpm-lock.yaml
    # resolved is the pin, and every biome.json $schema must name that release.
    "biome": ("PNPM_LOCK", "BIOME_CONFIGS"),
}


def _surface_files(tool: str) -> list[Path]:
    """Return the surfaces a tool's pin must appear on, from the current constants."""
    out: list[Path] = []
    for name in SURFACES[tool]:
        value = globals()[name]
        out.extend(value if isinstance(value, tuple) else (value,))
    return out


def _pin_forms(tool: str, version: str) -> list[re.Pattern[str]]:
    """Every literal shape a pin of ``tool@version`` takes on some surface."""
    t, v = re.escape(tool), re.escape(version)
    forms = [
        rf"\b{t}@{v}\b",  # uvx tool@version
        rf"\b{t}=={v}\b",  # uvx tool==version
        rf'name = "{t}"\nversion = "{v}"',  # uv.lock [[package]] block
    ]
    if tool == "ruff":
        forms.append(rf"ruff-pre-commit\n\s*rev:\s*v{v}\b")  # the pre-commit rev
    if tool == "biome":
        forms.append(rf"'@biomejs/biome@{v}':")  # pnpm-lock.yaml resolution
        forms.append(rf"biomejs\.dev/schemas/{v}/schema\.json")  # biome.json $schema
    return [re.compile(form) for form in forms]


def _executable_text(text: str) -> str:
    """Return the file text with comments removed — prose cannot pin a tool.

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
    forms = _pin_forms(tool, version)
    out: list[Path] = []
    for surface in _surface_files(tool):
        text = _executable_text(surface.read_text(encoding="utf-8"))
        if not any(form.search(text) for form in forms):
            out.append(surface)
    return out


def main(argv: list[str]) -> int:
    """Report every surface whose pin drifted from EXPECTED; return the exit code."""
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
                        f"{tool}=={version} for uv-tool-run, the lockfile resolution / "
                        f"biome.json $schema for biome) — or bump EXPECTED "
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
