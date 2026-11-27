"""Reject a ``# pragma: no mutate`` that mutmut never honours.

mutmut 3 reads a no-mutate pragma in two ways only. A trailing pragma covers the
expressions that start on its line. A comment-only ``start`` / ``end`` / ``block``
counts only between statements. Every other placement is silently ignored, so the
mutant it was written for survives and reds the mutation lane:

1. a comment-only pragma inside brackets (a list, dict or call spread over lines);
2. a comment-only pragma with no start/end/block token: it marks just its empty line;
3. a trailing pragma on a line of closing brackets that does not end the statement
   (one that does marks the statement's first line, which mutmut honours);
4. a trailing pragma on a plain name argument of a call opened on an earlier line, or
   on a keyword argument whose value holds nothing mutmut mutates (names, attributes,
   f-strings) of a call whose own line carries no pragma: an argument's replace-with-None
   and drop mutations are mutants of the call node, so they belong to the call's line.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import io
import keyword
from pathlib import Path
import re
import tokenize

from _common import Violation

RULE = "mutation-pragmas"
WHY = "mutmut ignores a no-mutate pragma in these places, so the mutant it names survives"
DOC = "tools/lints/README.md#mutation-pragmas"

_PRAGMA = re.compile(r"#\s*pragma:.*no mutate")
_CONTEXT_TOKENS = frozenset({"start", "end", "block"})
_ONLY_CLOSERS = re.compile(r"^[\s)\]},]*$")
# A name or attribute argument holds nothing mutmut mutates on its own line.
_PLAIN_ARGUMENT = re.compile(r"^\s*(\w+=)?[\w.]+,?\s*$")
# A keyword argument's own line holds only its value's mutants; kw=None and drop are the call's.
_KEYWORD_ARGUMENT = re.compile(r"^\s*\w+=(?!=)(?P<value>.*?),?\s*$")
# Nodes mutmut mutates; an f-string's text and a plain name are not among them.
_MUTATED = (ast.Constant, ast.UnaryOp, ast.BinOp, ast.BoolOp, ast.Compare, ast.Call, ast.Lambda)
_OPENERS = {"(": ")", "[": "]", "{": "}"}
_CLOSERS = frozenset(_OPENERS.values())


@dataclass(frozen=True)
class _Open:
    char: str
    line: int
    is_call: bool
    # The call's own line carries a pragma, so its argument mutants are already skipped.
    covered: bool


def _pragma_token(comment: str) -> str | None:
    """Return the start/end/block token after 'no mutate', or None for a bare pragma."""
    tail = comment.partition("no mutate")[2].lstrip(": ").split(",", 1)[0].split()
    return tail[0] if tail and tail[0] in _CONTEXT_TOKENS else None


def _opens_call(previous: tokenize.TokenInfo | None) -> bool:
    if previous is None:
        return False
    if previous.type == tokenize.NAME:
        return not keyword.iskeyword(previous.string)
    return previous.string in {")", "]"}


def _keyword_value_mutates_nothing(code: str) -> bool:
    """Return whether code is a whole keyword argument whose value gives mutmut nothing to mutate."""
    match = _KEYWORD_ARGUMENT.match(code)
    if match is None:
        return False
    try:
        value = ast.parse(match["value"], mode="eval")
    except SyntaxError:
        return False
    in_fstrings = {
        id(part)
        for node in ast.walk(value)
        if isinstance(node, ast.JoinedStr)
        for part in node.values
    }
    return not any(
        isinstance(node, _MUTATED) and not (isinstance(node, ast.Constant) and node.value is None)
        for node in ast.walk(value)
        if id(node) not in in_fstrings
    )


def _misplaced(comment: tokenize.TokenInfo, stack: list[_Open], line_text: str) -> str | None:
    """Say why mutmut ignores this pragma, or None when it is honoured."""
    code = line_text[: comment.start[1]]
    if not code.strip():
        if stack:
            return "a comment-only pragma inside brackets is never seen by mutmut"
        if _pragma_token(comment.string) is None:
            return "a comment-only pragma without start/end/block marks only its own empty line"
        return None
    if stack and _ONLY_CLOSERS.match(code):
        return "a trailing pragma on a line of closing brackets inside an expression covers nothing"
    innermost = stack[-1] if stack else None
    if (
        innermost is not None
        and innermost.is_call
        and innermost.line < comment.start[0]
        and (
            _PLAIN_ARGUMENT.match(code)
            or (not innermost.covered and _keyword_value_mutates_nothing(code))
        )
    ):
        return (
            f"an argument's replace and drop mutations belong to the call on line "
            f"{innermost.line}, not to this line"
        )
    return None


def _scan(path: Path) -> list[Violation]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    stack: list[_Open] = []
    previous: tokenize.TokenInfo | None = None
    in_block = False
    violations: list[Violation] = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.OP and tok.string in _OPENERS:
            is_call = tok.string == "(" and _opens_call(previous)
            covered = in_block or bool(_PRAGMA.search(lines[tok.start[0] - 1]))
            stack.append(_Open(tok.string, tok.start[0], is_call, covered))
        elif tok.type == tokenize.OP and tok.string in _CLOSERS and stack:
            stack.pop()
        elif tok.type == tokenize.COMMENT and _PRAGMA.search(tok.string):
            if not stack and _pragma_token(tok.string) in {"start", "end"}:
                in_block = _pragma_token(tok.string) == "start"
            reason = _misplaced(tok, stack, lines[tok.start[0] - 1])
            if reason is not None:
                violations.append(
                    Violation(
                        path=path,
                        line=tok.start[0],
                        detail=reason,
                        fix=(
                            "put the pragma on the line where the mutated expression starts "
                            "(a call's first line for its arguments), or wrap the whole "
                            "statement in '# pragma: no mutate start' / '# pragma: no mutate end'"
                        ),
                    )
                )
        if tok.type not in {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE}:
            previous = tok
    return violations


def check(files: list[Path]) -> list[Violation]:
    """Return every pragma under app/ that mutmut would ignore."""
    return [v for path in files if "/app/" in path.as_posix() for v in _scan(path)]
