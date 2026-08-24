#!/usr/bin/env python3
"""Stateless suppression hygiene: every inline suppression carries its reason.

There is no baseline and no memory. Two stateless properties hold the line
instead, each enforced where it is cheapest:

1. HERE — a suppression may only exist inline, at the offending line, WITH a
   written reason. ``# type: ignore[arg-type]  # langgraph ships no stubs``.
   The reason is reviewed in the diff, lives where the code lives, and dies
   with the code. A directive without one fails here, at that exact line.

2. The compilers hunt staleness (not this script):
     - mypy runs with ``warn_unused_ignores = true``  -> dead ``# type: ignore``
     - ruff ships RUF100 (selected via the ``RUF`` family) -> dead ``# noqa``
     - biome ships ``suppressions/unused``            -> dead ``// biome-ignore``
   A suppression that no longer masks anything breaks the build on its own,
   which is strictly stronger than a growth ratchet: nothing can rot silently.

What counts as a reason: prose on the SAME line, after the rule codes. Another
tool directive (``NOSONAR ...``) does not count — it explains nothing. Quality
is review's job; presence is this script's.

Scanned kinds:
    noqa           -- ``# noqa[: codes]``      in *.py   (tokenize: real comments)
    type-ignore    -- ``# type: ignore[codes]`` in *.py  (never strings/docstrings)
    biome-ignore   -- ``// biome-ignore <rule>: reason`` in ts/tsx/js/jsx/mjs/cjs

The TS scanner has no stdlib parser: quote spans are blanked per line, then a
left-to-right walk tracks template-literal state across lines and recognizes
``//`` comments before backticks can toggle state (a backtick inside a comment
is inert). Accepted imprecision (no stdlib TS/JS parser exists): a backtick
inside a ``${...}`` expression, or a template body line whose paired quotes
surround the closing backtick.

Usage::

    python3 tools/lints/check_suppressions.py            # whole tree
    python3 tools/lints/check_suppressions.py app/foo.py # scope to paths

Stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tokenize

from _common import Violation, report_rule

RULE = "suppression-hygiene"
WHY = (
    "an inline suppression without a written reason is debt nobody can judge — "
    "state WHY at the line, and let mypy/RUF100/biome catch the ones that rot"
)
DOC = "tools/lints/README.md#suppression-hygiene"

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parents[1]

_TS_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css"}
_TRACKED_GLOBS = ("*.py", "*.ts", "*.tsx", "*.js", "*.jsx", "*.mjs", "*.cjs", "*.css")

_NOQA_RE = re.compile(r"#\s*noqa\b")
_TYPE_IGNORE_RE = re.compile(r"#\s*type:\s*ignore\b")
_BIOME_IGNORE_ANY_RE = re.compile(r"/{1,2}\s*\**\s*biome-ignore\b")

#: Stripped off the front of a comment to leave the reason prose behind.
_DIRECTIVE_PREFIXES = (
    re.compile(r"^#\s*type:\s*ignore(?:\s*\[[^\]]*\])?\s*"),
    re.compile(r"^#\s*noqa(?::\s*[A-Z]+[0-9]+(?:,\s*[A-Z]+[0-9]+)*)?\s*"),
)

#: Whole-file kill switches — one comment disables a checker for every line
#: in the file. They demand a reason like any other suppression.
_FILE_LEVEL_RE = re.compile(r"^#\s*(?:mypy:\s*ignore-errors|(?:ruff|flake8):\s*noqa)\b")

#: Suffixes that name another tool's directive, not a reason.
_NON_REASON_SUFFIXES = (re.compile(r"^#\s*NOSONAR\b.*$"),)

#: A reason must be at least this many characters of actual text. The bar is
#: presence, not eloquence — review judges the wording.
_MIN_REASON_LEN = 8


@dataclass(frozen=True)
class Hit:
    """One suppression comment found in the tree."""

    kind: str
    line: int
    text: str


def _tracked_files(scoped: list[Path]) -> list[Path]:
    """Every git-tracked source file the scan cares about (skips untracked/ignored),
    optionally narrowed to the given paths."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git not found on PATH — the scanner needs `git ls-files`")
    # argv is a constant list plus a fixed glob tuple (no user input), and
    # `git` is resolved to an absolute path via shutil.which above, so
    # shell=False is safe here.
    out = subprocess.run(  # nosec B603
        [git, "ls-files", "-z", "--", *_TRACKED_GLOBS],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    files = [REPO_ROOT / p for p in out.decode().split("\0") if p]
    if not scoped:
        return files
    allowed = [p.resolve() for p in scoped]
    return [f for f in files if any(f.is_relative_to(d) for d in allowed)]


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _reason_of(comment: str) -> str | None:
    """The reason prose in a Python directive comment, or None if absent.

    Finds the directive anywhere in the comment (another tool's directive, e.g.
    ``# NOSONAR …``, may precede it on the same line), strips the directive
    prefix (``# noqa: B006``, ``# type: ignore[arg-type]``) and any further
    other-tool directives; what remains must be real prose.
    """
    m = re.search(
        r"#\s*(?:noqa|type:\s*ignore|mypy:\s*ignore-errors|(?:ruff|flake8):\s*noqa)\b",
        comment,
    )
    if not m:
        return None
    rest = comment[m.start() :]
    stripped = False
    level = _FILE_LEVEL_RE.match(rest)
    if level:
        rest = rest[level.end() :].lstrip()
        stripped = True
    for prefix in _DIRECTIVE_PREFIXES:
        if prefix.match(rest):
            rest = prefix.sub("", rest, count=1)
            stripped = True
            break
    if not stripped:
        return None
    for non_reason in _NON_REASON_SUFFIXES:
        if non_reason.match(rest):
            return None
    return rest.strip()


def _has_reason(comment: str) -> bool:
    reason = _reason_of(comment)
    return reason is not None and len(reason) >= _MIN_REASON_LEN


def _scan_python_comments(path: Path) -> list[Hit]:
    """Directives that appear in real ``#`` comments only — never ones that
    merely appear inside a string or docstring literal.
    """
    text = _read_text(path)
    if text is None:
        return []
    hits: list[Hit] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type != tokenize.COMMENT:
                continue
            kind = None
            if _FILE_LEVEL_RE.match(tok.string.strip()):
                kind = "file-level"
            elif _TYPE_IGNORE_RE.search(tok.string):
                kind = "type-ignore"
            elif _NOQA_RE.search(tok.string):
                kind = "noqa"
            if kind:
                hits.append(Hit(kind, tok.start[0], tok.string.strip()))
    except (tokenize.TokenError, SyntaxError) as exc:
        raise RuntimeError(
            f"suppression scan: failed to tokenize {path.relative_to(REPO_ROOT)} — {exc}"
        ) from exc
    return hits


def _split_comment(line: str, in_template: bool) -> tuple[str, bool]:
    """The ``//`` comment portion of a TS/JS line (or ``""``), plus the
    template-literal state carried into the next line.

    Left-to-right walk over a line whose same-line quote spans are already
    blanked: in code, ``//`` starts a comment (the rest of the line, including
    any backticks in it, is inert) and an unescaped backtick enters a template;
    in a template, an unescaped backtick exits it. Escapes are counted, so
    ``\\\\``` (escaped backslash, real backtick) toggles and ``\\``` does not.
    Remaining accepted imprecision: a backtick inside ``${...}`` (see module
    docstring).
    """
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "\\":
            i += 2  # the escaped character never toggles anything
            continue
        if in_template:
            if ch == "`":
                in_template = False
            i += 1
            continue
        if ch == "`":
            in_template = True
            i += 1
            continue
        if ch == "/" and i + 1 < n and line[i + 1] == "/":
            return line[i:], in_template
        i += 1
    return "", in_template


# Matches a single/double-quoted span on one line, blanked before the
# backtick walk so quote contents can't toggle template state. Backticks are
# handled exclusively by _split_comment.
_QUOTED_SPAN_RE = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')


def _scan_ts_comments(path: Path) -> list[Hit]:
    """``// biome-ignore`` in real ``//`` comments only — never inside a string
    literal, including multi-line template literals (see ``_split_comment``).
    """
    text = _read_text(path)
    if text is None:
        return []
    hits: list[Hit] = []
    in_template = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        blanked = _QUOTED_SPAN_RE.sub(lambda m: " " * len(m.group()), line)
        comment, in_template = _split_comment(blanked, in_template)
        source_form = comment or blanked
        if source_form and _BIOME_IGNORE_ANY_RE.search(source_form):
            # Normalize every shape (// , /* , /** , JSX {/* */) to
            # "// biome-ignore …" so reason extraction has one canonical form.
            idx = source_form.index("biome-ignore")
            body = source_form[idx:].split("*/")[0].rstrip()
            norm = ("// " + body).strip()
            hits.append(Hit("biome-ignore", lineno, norm))
    return hits


def _biome_reason(comment: str) -> str | None:
    """The reason after ``// biome-ignore <rule>:`` — biome's own convention."""
    m = re.search(r"biome-ignore(?:-[a-z]+)?\s+\S+:?\s*(.*)$", comment)
    if not m:
        return None
    return m.group(1).strip()


def _has_ts_reason(hit: Hit) -> bool:
    reason = _biome_reason(hit.text)
    return reason is not None and len(reason) >= _MIN_REASON_LEN


def scan_tree(scoped: list[Path]) -> dict[str, list[Hit]]:
    """Suppression hits grouped by repo-relative path."""
    grouped: dict[str, list[Hit]] = {}
    for path in _tracked_files(scoped):
        hits = _scan_file(path)
        if hits:
            grouped[path.relative_to(REPO_ROOT).as_posix()] = hits
    return grouped


def _scan_file(path: Path) -> list[Hit]:
    if path.suffix == ".py":
        return _scan_python_comments(path)
    if path.suffix in _TS_SUFFIXES:
        return _scan_ts_comments(path)
    return []


def main(argv: list[str]) -> int:
    """Fail on any inline suppression that carries no written reason."""
    scoped = [Path(a) for a in argv if not a.startswith("-")]
    grouped = scan_tree(scoped)

    violations: list[Violation] = []
    for rel, hits in sorted(grouped.items()):
        for hit in hits:
            ok = _has_reason(hit.text) if hit.kind != "biome-ignore" else _has_ts_reason(hit)
            if ok:
                continue
            print(f"::error file={rel},line={hit.line}::{hit.kind} without a reason")
            violations.append(
                Violation(
                    path=Path(rel),
                    line=hit.line,
                    detail=f"[{hit.kind}] {hit.text}",
                    fix=(
                        "append the WHY on this same line after the rule code "
                        "(e.g. '# langgraph ships no stubs upstream') — or delete "
                        "the suppression if it no longer masks anything"
                    ),
                )
            )

    if violations:
        report_rule(RULE, WHY, DOC, violations)
        print(
            f"\n{len(violations)} suppression(s) without a reason. "
            "Every inline suppression must say WHY on its own line.",
            file=sys.stderr,
        )
        return 1

    total = sum(len(hits) for hits in grouped.values())
    scope = "scoped paths" if scoped else "whole tree"
    print(f"{RULE}: OK — {total} suppression(s) in {scope}, all carry a reason")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
