"""A comment is one line of why at the point of surprise, not a paragraph.

  CM1  more than 3 consecutive comment lines — keep the fact, drop the story
  CM2  a banner (``# ----``, ``# ====``) or ``# Step N`` inside a function
       body — narration of a function that wants splitting. Module- and
       class-level banners are allowed: a constants file or a 300-field
       Settings class is supposed to be sectioned.
  CM3  a comment whose only content is the statement directly below it

Pragmas (``noqa``, ``type:``, ``pragma``, ``fmt``, ``nosec``…) and trailing
comments never count. No allowlist and no escape hatch — a finding is fixed by
deleting or shortening.
"""

from __future__ import annotations

import ast
import io
from pathlib import Path
import re
import tokenize

from _common import Violation

RULE = "comment-content"
WHY = (
    "a comment wall above a constant or a numbered narration inside a function "
    "hides the one line that mattered; comments regain meaning when they are rare"
)
DOC = "tools/lints/README.md#comment-content"

INCLUDES_TESTS = True

MAX_CONSECUTIVE = 3

_PRAGMA_PREFIXES = (
    "#!",
    "# noqa",
    "# type:",
    "# ruff",
    "# pragma",
    "# fmt",
    "# pylint",
    "# mypy",
    "# nosec",
    "# pyright",
    "# NOSONAR",
)
_BANNER = re.compile(r"^#\s*([-=#*~_]{3,}|step\s*\d+\b)", re.I)
_FILLER = frozenset(
    [
        "the",
        "a",
        "an",
        "of",
        "to",
        "for",
        "and",
        "or",
        "in",
        "on",
        "is",
        "this",
        "that",
        "with",
        "from",
        "if",
        "by",
        "its",
        "it",
    ]
)


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", text.lower()) if w and w not in _FILLER}


def _function_spans(tree: ast.AST) -> list[tuple[int, int]]:
    return [
        (node.lineno, node.end_lineno or node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _own_line_comments(src: str) -> list[tuple[int, str]]:
    """``(line, text)`` for every comment that owns its line and is not a pragma."""
    lines = src.splitlines()
    out: list[tuple[int, str]] = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type != tokenize.COMMENT or tok.string.startswith(_PRAGMA_PREFIXES):
            continue
        line = tok.start[0]
        if lines[line - 1].lstrip().startswith("#"):
            out.append((line, tok.string))
    return out


def _statement_directly_below(lines: list[str], line: int) -> str:
    """Return the code on the line after ``line`` (1-based), or '' when it is not code."""
    below = lines[line].strip() if line < len(lines) else ""
    return "" if below.startswith("#") else below


def _check_file(path: Path) -> list[Violation]:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    spans = _function_spans(ast.parse(src, filename=str(path)))
    out: list[Violation] = []

    def flag(line: int, code: str, detail: str, fix: str) -> None:
        out.append(Violation(path=path, line=line, detail=f"{code}: {detail}", fix=fix))

    run, prev = 0, -2
    for line, text in _own_line_comments(src):
        run = run + 1 if line == prev + 1 else 1
        prev = line
        if run == MAX_CONSECUTIVE + 1:
            flag(
                line - MAX_CONSECUTIVE,
                "CM1",
                f"comment block longer than {MAX_CONSECUTIVE} lines",
                "keep the numbers and constraints, delete the narrative; the rest is the PR description",
            )
        if _BANNER.match(text) and any(start < line <= end for start, end in spans):
            flag(
                line,
                "CM2",
                "banner or step comment inside a function",
                "split the function instead of sectioning it",
            )
        comment_words = _words(text.lstrip("# "))
        if len(comment_words) >= 2 and comment_words <= _words(
            _statement_directly_below(lines, line)
        ):
            flag(line, "CM3", "comment only restates the line below it", "delete it")
    return out


def check(files: list[Path]) -> list[Violation]:
    """Return comment-content violations across ``files``."""
    violations: list[Violation] = []
    for path in files:
        violations.extend(_check_file(path))
    return violations
