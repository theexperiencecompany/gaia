#!/usr/bin/env python3
"""Tool-version skew guard: every surface that runs a linter runs the SAME pin.

The whole point of pinning is that "passed locally" means "passes CI". This
check fails when the versions drift apart across the surfaces in SURFACES:
both pre-commit configs, code-quality.yml, the local lane table
(scripts/dev/verify-lanes.json), the root package.json quality scripts, the
api mise tasks and taskipy scripts, the ignore-staleness guard's own ruff
invocation, uv.lock, for biome pnpm-lock.yaml plus every biome.json schema, and
for uv itself mise.toml, the setup-uv action and the app Dockerfiles.

Node is the exception to the EXPECTED table, because it is derived rather than
repeated: ``.node-version`` is the single declaration, mise reads it (via
``idiomatic_version_file_enable_tools``), actions/setup-node reads it (via
``node-version-file``) and the Dagger image reads it at run time. The only
permitted mirror is one ``ARG NODE_VERSION`` default per Dockerfile, since
Docker cannot read a file in a FROM line. Any other hardcoded node version in
the scanned surfaces is a failure.

Single source of truth is the EXPECTED table below; bump it in the same commit
that bumps any invocation, or this fails and tells you which side drifted.

Usage::

    python3 tools/lints/check_tool_pins.py

Stdlib only.
"""

from __future__ import annotations

import fnmatch
import os
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
ROOT_MISE = REPO_ROOT / "mise.toml"
API_MISE = REPO_ROOT / "apps/api/mise.toml"
API_PYPROJECT = REPO_ROOT / "apps/api/pyproject.toml"
PNPM_LOCK = REPO_ROOT / "pnpm-lock.yaml"
IGNORE_STALENESS = REPO_ROOT / "tools/lints/check_ignore_staleness.py"
UV_LOCK = REPO_ROOT / "uv.lock"
SETUP_UV = REPO_ROOT / ".github/actions/setup-uv/action.yml"
# Node is derived, not repeated: .node-version is the single declaration and
# every consumer reads it. These are the surfaces that must reference the file
# rather than restate the version.
NODE_VERSION_FILE = REPO_ROOT / ".node-version"
NODE_FILE_REFERENCE_SURFACES = (
    REPO_ROOT / ".github/actions/setup-node-pnpm/action.yml",
    REPO_ROOT / ".github/workflows/publish-cli.yml",
    REPO_ROOT / ".github/workflows/desktop-release.yml",
)
# Docker cannot read a file in a FROM line, and the Dagger module would need its
# sync container builders turned async to read one. Both therefore carry a
# single mirrored literal, and the guard ties each one back to .node-version so
# a stale mirror fails CI instead of shipping.
NODE_MIRRORS = (
    (REPO_ROOT / "infra/docker/ci-base.Dockerfile", r"^ARG\s+NODE_VERSION=(\d+\.\d+\.\d+)\s*$"),
    (REPO_ROOT / "apps/web/Dockerfile", r"^ARG\s+NODE_VERSION=(\d+\.\d+\.\d+)\s*$"),
    (REPO_ROOT / "apps/bots/Dockerfile", r"^ARG\s+NODE_VERSION=(\d+\.\d+\.\d+)\s*$"),
    (REPO_ROOT / ".dagger/src/gaia_ci/main.py", r'\.from_\("node:(\d+\.\d+\.\d+)-'),
)
# Every Dockerfile that must take its tag from the ARG rather than restating it.
NODE_DOCKERFILES = (
    REPO_ROOT / "infra/docker/ci-base.Dockerfile",
    REPO_ROOT / "apps/web/Dockerfile",
    REPO_ROOT / "apps/bots/Dockerfile",
)
# Bounded set of files that could reintroduce a hardcoded node version.
NODE_LITERAL_SCAN = (
    "mise.toml",
    "apps/*/mise.toml",
    "docs/mise.toml",
    ".github/workflows/*.yml",
    ".github/actions/*/action.yml",
    "**/Dockerfile",
    "**/*.Dockerfile",
    ".dagger/src/**/*.py",
)
_NODE_SKIP = ("node_modules", ".venv", ".git", ".nx", ".next", "dist")
UV_DOCKERFILES = (
    REPO_ROOT / "apps/api/Dockerfile",
    REPO_ROOT / "apps/voice-agent/Dockerfile",
)
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
    "uv": "0.10.6",
}

# Where each expectation must literally appear. Values are the module
# constants naming the surface files (a Path, or a tuple of Paths), resolved
# at call time (not import time) so the guard always reads the constants it
# reports against — and so the tests can monkeypatch them onto fixture files.
SURFACES = {
    # `uv run ruff` surfaces (nx targets, the Claude hook, package.json) are
    # pinned by uv.lock; the uvx ones name the version themselves.
    # ROOT_MISE holds the whole-repo `lint:py` tasks, which run the python-ruff
    # lane's command verbatim. Without it here the guard would pass while those
    # tasks had silently drifted to a different ruff than the lane they mirror.
    "ruff": (
        "PRE_COMMIT",
        "ROOT_PRE_COMMIT",
        "CODE_QUALITY",
        "IGNORE_STALENESS",
        "UV_LOCK",
        "ROOT_MISE",
    ),
    # The api mypy hook runs `uv run mypy`, so the lockfile IS the pin.
    "mypy": ("UV_LOCK",),
    "bandit": ("PRE_COMMIT", "CODE_QUALITY", "VERIFY_LANES", "API_MISE", "API_PYPROJECT"),
    "pip-audit": ("PRE_COMMIT", "CODE_QUALITY", "VERIFY_LANES", "API_MISE", "API_PYPROJECT"),
    "interrogate": ("CODE_QUALITY", "VERIFY_LANES", "ROOT_PACKAGE_JSON"),
    "xenon": ("CODE_QUALITY", "VERIFY_LANES", "ROOT_PACKAGE_JSON"),
    # package.json keeps syncpack's caret policy; the version pnpm-lock.yaml
    # resolved is the pin, and every biome.json $schema must name that release.
    "biome": ("PNPM_LOCK", "BIOME_CONFIGS"),
    # uv writes and reads uv.lock, so a local uv other than CI's re-resolves it differently.
    "uv": ("ROOT_MISE", "SETUP_UV", "UV_DOCKERFILES"),
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
    if tool == "uv":
        forms.append(rf'^uv = "{v}"')  # mise.toml [tools]
        forms.append(rf'^\s*default: "{v}"')  # the setup-uv action's version input
        forms.append(rf"astral-sh/uv:{v}\b")  # Dockerfile COPY --from
    if tool == "biome":
        forms.append(rf"'@biomejs/biome@{v}':")  # pnpm-lock.yaml resolution
        forms.append(rf"biomejs\.dev/schemas/{v}/schema\.json")  # biome.json $schema
    return [re.compile(form, re.MULTILINE) for form in forms]


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


# ── Node: one declaration, everything else derives from it ───────────────────
# The node version used to be restated on nine surfaces across four commits and
# they drifted. It is now declared once in .node-version, which mise reads
# (via idiomatic_version_file_enable_tools), actions/setup-node reads (via
# node-version-file) and the Dagger image reads at run time. These checks turn a
# second declaration into a build failure instead of a bad afternoon later.
_NODE_FILE_FORM = re.compile(r"^\d+\.\d+\.\d+$")
_NODE_FILE_REF = re.compile(r"""node-version-file:\s*['"]?\.node-version""")
_NODE_MISE_SETTING = re.compile(r'idiomatic_version_file_enable_tools\s*=\s*\[[^\]]*"node"')
_NODE_ARG_USED = re.compile(r"^FROM\s+node:\$\{NODE_VERSION\}", re.MULTILINE)
# Any of these on an executable line is a second declaration of the version.
# `ARG NODE_VERSION=1.2.3` matches none of them: it is the one allowed mirror.
_NODE_LITERALS = (
    re.compile(r'\bnode\s*=\s*"\d+(?:\.\d+)*"'),  # mise [tools]
    re.compile(r'\bnode-version:\s*"?\d+(?:\.\d+)*"?'),  # setup-node literal
    re.compile(r"\bnode:\d+(?:\.\d+)*"),  # image tag
)


def _node_version() -> str | None:
    """Return the declared node version, or None when .node-version is absent."""
    if not NODE_VERSION_FILE.is_file():
        return None
    text = NODE_VERSION_FILE.read_text(encoding="utf-8").strip()
    return text if _NODE_FILE_FORM.match(text) else None


# ── pnpm: package.json#packageManager is the declaration ─────────────────────
# corepack already treats that field as the source of truth, so the rest are
# mirrors. Three of them cannot derive (the Dockerfiles run `corepack prepare`
# before package.json is in the image, and ci-base has no repo at all), so the
# guard ties them back the same way it does for node.
_PNPM_PACKAGE_MANAGER = re.compile(r'"packageManager"\s*:\s*"pnpm@(\d+\.\d+\.\d+)"')
_PNPM_MIRRORS = (
    (
        REPO_ROOT / "infra/docker/ci-base.Dockerfile",
        r"corepack prepare pnpm@(\d+\.\d+\.\d+)",
    ),
    (REPO_ROOT / "apps/web/Dockerfile", r"corepack prepare pnpm@(\d+\.\d+\.\d+)"),
    (REPO_ROOT / "apps/bots/Dockerfile", r"corepack prepare pnpm@(\d+\.\d+\.\d+)"),
    (REPO_ROOT / ".dagger/src/gaia_ci/main.py", r"corepack prepare pnpm@(\d+\.\d+\.\d+)"),
    (
        REPO_ROOT / ".github/actions/setup-node-pnpm/action.yml",
        r'PNPM_VERSION:\s*"(\d+\.\d+\.\d+)"',
    ),
)
_PNPM_ACTION_SETUP = "pnpm/action-setup"


def _pnpm_version() -> str | None:
    """Return the pnpm version package.json declares to corepack."""
    if not ROOT_PACKAGE_JSON.is_file():
        return None
    match = _PNPM_PACKAGE_MANAGER.search(ROOT_PACKAGE_JSON.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _pnpm_declaration_violation() -> Violation:
    """Build the violation for a missing packageManager declaration."""
    return Violation(
        path=ROOT_PACKAGE_JSON,
        line=1,
        detail='no `"packageManager": "pnpm@x.y.z"` declaration',
        fix="add it — corepack reads this field, so it is the one place the pnpm "
        "version is declared",
    )


def _pnpm_mirror_violation(path: Path, pattern: str, version: str) -> Violation | None:
    """One mirror that is missing or names a different release."""
    if not path.is_file():
        return None
    text = _executable_text(path.read_text(encoding="utf-8"))
    match = re.compile(pattern, re.MULTILINE).search(text)
    if match is None:
        return Violation(
            path=path,
            line=1,
            detail="no pnpm version mirror found",
            fix=f"mirror package.json's pnpm@{version} here",
        )
    if match.group(1) != version:
        return Violation(
            path=path,
            line=1,
            detail=f"mirrors pnpm {match.group(1)}, package.json declares {version}",
            fix=f"set it to {version} — package.json#packageManager is the declaration",
        )
    return None


def _pnpm_workflow_violation(workflow: Path) -> Violation | None:
    """Detect an explicit `version:` on pnpm/action-setup, which overrides package.json.

    The action reads packageManager when the input is absent, so naming a
    version here is a second declaration the guard cannot otherwise see.
    """
    lines = workflow.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if _PNPM_ACTION_SETUP not in line or line.lstrip().startswith("#"):
            continue
        step_indent = len(line) - len(line.lstrip())
        for follow in lines[index + 1 : index + 8]:
            stripped = follow.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # The next list item ends this step.
            if stripped.startswith("-") and (len(follow) - len(follow.lstrip())) <= step_indent:
                break
            explicit = re.match(r"^version:\s*[\"']?(\d+\.\d+\.\d+)", stripped)
            if explicit:
                return Violation(
                    path=workflow,
                    line=index + 1,
                    detail=f"pnpm/action-setup pins version {explicit.group(1)} explicitly",
                    fix="drop the `version:` input — the action reads "
                    "package.json#packageManager, so the pin lives in one place",
                )
    return None


def _pnpm_violations() -> list[Violation]:
    """Report every pnpm mirror that disagrees, or an explicit action-setup pin."""
    version = _pnpm_version()
    if version is None:
        return [_pnpm_declaration_violation()]
    found = [_pnpm_mirror_violation(p, pat, version) for p, pat in _PNPM_MIRRORS]
    found += [
        _pnpm_workflow_violation(w)
        for w in sorted((REPO_ROOT / ".github/workflows").glob("*.yml"))
    ]
    return [v for v in found if v is not None]


def _rel_matches(rel: str, pattern: str) -> bool:
    """Match a repo-relative path against a scan pattern.

    fnmatch's ``*`` already crosses ``/``, but a leading ``**/`` must also match
    a file at the repo root (``**/mise.toml`` has to match ``mise.toml``), which
    fnmatch alone does not do.
    """
    if fnmatch.fnmatch(rel, pattern):
        return True
    return pattern.startswith("**/") and fnmatch.fnmatch(rel, pattern[3:])


def _node_scan_files() -> list[Path]:
    """Every file that could reintroduce a hardcoded node version.

    Walks with the skip dirs pruned instead of using a ``**`` glob: a
    ``**/Dockerfile`` glob descends node_modules, which on an installed
    checkout is millions of files for a lint that must stay pre-commit fast.
    """
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _NODE_SKIP]
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(REPO_ROOT).as_posix()
            if any(_rel_matches(rel, pattern) for pattern in NODE_LITERAL_SCAN):
                out.append(path)
    return sorted(out)


def _node_declaration_violation() -> Violation:
    """Build the violation for a missing .node-version declaration."""
    return Violation(
        path=NODE_VERSION_FILE,
        line=1,
        detail=".node-version is missing or is not a bare x.y.z version",
        fix="create .node-version with one line, e.g. 24.22.1 — it is the only place "
        "the node version is declared",
    )


def _node_reference_violation(surface: Path) -> Violation | None:
    """Detect a surface that restates the version instead of reading the file."""
    text = _executable_text(surface.read_text(encoding="utf-8"))
    if _NODE_FILE_REF.search(text):
        return None
    return Violation(
        path=surface,
        line=1,
        detail="does not read the node version from .node-version",
        fix='replace the version with `node-version-file: ".node-version"` so this '
        "surface cannot disagree with the repo",
    )


def _node_mise_setting_violation() -> Violation | None:
    """Mise ignores .node-version unless idiomatic version files are enabled."""
    mise = _executable_text(ROOT_MISE.read_text(encoding="utf-8"))
    if _NODE_MISE_SETTING.search(mise):
        return None
    return Violation(
        path=ROOT_MISE,
        line=1,
        detail="idiomatic version files are not enabled, so mise ignores .node-version",
        fix='add `idiomatic_version_file_enable_tools = ["node"]` under [settings]',
    )


def _node_mirror_violation(path: Path, pattern: str, version: str) -> Violation | None:
    """One mirrored literal that is missing, stale, or joined by a stray tag."""
    if not path.is_file():
        return None
    text = _executable_text(path.read_text(encoding="utf-8"))
    form = re.compile(pattern, re.MULTILINE)
    match = form.search(text)
    if match is None:
        return Violation(
            path=path,
            line=1,
            detail="no node version mirror found",
            fix=f"mirror .node-version here ({version}) — this file cannot read the file "
            "at build time, so the guard ties it back",
        )
    if match.group(1) != version:
        return Violation(
            path=path,
            line=1,
            detail=f"mirrors node {match.group(1)}, .node-version is {version}",
            fix=f"set it to {version} — this file cannot read .node-version, so the guard "
            "exists to keep the two identical",
        )
    # One permitted mirror per file is not enough: a second stage can carry its
    # own tag (a hardcoded `FROM node:24-alpine AS runner` beside a
    # parameterised base). Strip the permitted form; anything left that names a
    # version is drift.
    residual = form.sub("", text)
    for literal in _NODE_LITERALS:
        stray = literal.search(residual)
        if stray:
            return Violation(
                path=path,
                line=1,
                detail=f"hardcodes a node version outside the mirror: {stray.group(0)!r}",
                fix="use the single mirror in this file — `ARG NODE_VERSION` + "
                "`FROM node:${NODE_VERSION}` in a Dockerfile",
            )
    return None


def _node_from_violation(dockerfile: Path) -> Violation | None:
    """Detect a Dockerfile whose FROM restates a tag instead of using the ARG."""
    if not dockerfile.is_file():
        return None
    text = _executable_text(dockerfile.read_text(encoding="utf-8"))
    if _NODE_ARG_USED.search(text):
        return None
    return Violation(
        path=dockerfile,
        line=1,
        detail="FROM does not use ${NODE_VERSION}",
        fix="write `FROM node:${NODE_VERSION}-<variant>` so the tag comes from the ARG",
    )


def _node_stray_violation(path: Path, mirrors: set[Path]) -> Violation | None:
    """Detect a hardcoded version anywhere outside the permitted mirrors."""
    if path.resolve() in mirrors:
        return None
    text = _executable_text(path.read_text(encoding="utf-8"))
    for form in _NODE_LITERALS:
        match = form.search(text)
        if match:
            return Violation(
                path=path,
                line=1,
                detail=f"hardcodes a node version: {match.group(0)!r}",
                fix="derive it instead — .node-version is the single declaration "
                "(mise reads it, CI uses node-version-file, images use ARG NODE_VERSION)",
            )
    return None


def _node_violations() -> list[Violation]:
    """Report every place that declares a node version besides .node-version."""
    version = _node_version()
    if version is None:
        return [_node_declaration_violation()]
    mirrors = {path.resolve() for path, _ in NODE_MIRRORS}
    found = [_node_reference_violation(s) for s in NODE_FILE_REFERENCE_SURFACES]
    found.append(_node_mise_setting_violation())
    found += [_node_mirror_violation(p, pat, version) for p, pat in NODE_MIRRORS]
    found += [_node_from_violation(d) for d in NODE_DOCKERFILES]
    found += [_node_stray_violation(p, mirrors) for p in _node_scan_files()]
    return [v for v in found if v is not None]


def main(argv: list[str]) -> int:
    """Report every drift from EXPECTED or .node-version; return the exit code."""
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
    violations.extend(_node_violations())
    violations.extend(_pnpm_violations())

    if violations:
        report_rule(RULE, WHY, DOC, violations)
        print(f"\n{len(violations)} unpinned tool invocation(s).", file=sys.stderr)
        return 1

    node = _node_version() or "?"
    pnpm = _pnpm_version() or "?"
    print(
        f"{RULE}: OK — {len(EXPECTED)} tool pins consistent across hooks and CI, "
        f"node {node} in .node-version, pnpm {pnpm} in package.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
