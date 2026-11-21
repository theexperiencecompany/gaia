"""Reject a ``# pragma: no mutate`` that mutmut never honours.

mutmut 3 reads a no-mutate pragma in two ways only. A trailing pragma covers the
expressions that start on its line. A comment-only ``start`` / ``end`` / ``block``
counts only between statements. Every other placement is silently ignored, so the
mutant it was written for survives and reds the mutation lane:

1. a comment-only pragma inside brackets (a list, dict or call spread over lines);
2. a comment-only pragma with no start/end/block token: it marks just its empty line;
3. a trailing pragma on a line of closing brackets that does not end the statement
   (one that does marks the statement's first line, which mutmut honours);
4. a trailing pragma on a plain name argument of a call opened on an earlier line:
   the argument's replace-with-None and drop mutations belong to the call's line.
"""

from __future__ import annotations

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
_OPENERS = {"(": ")", "[": "]", "{": "}"}
_CLOSERS = frozenset(_OPENERS.values())


@dataclass(frozen=True)
class _Open:
    char: str
    line: int
    is_call: bool


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
        and _PLAIN_ARGUMENT.match(code)
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
    violations: list[Violation] = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.OP and tok.string in _OPENERS:
            is_call = tok.string == "(" and _opens_call(previous)
            stack.append(_Open(tok.string, tok.start[0], is_call))
        elif tok.type == tokenize.OP and tok.string in _CLOSERS and stack:
            stack.pop()
        elif tok.type == tokenize.COMMENT and _PRAGMA.search(tok.string):
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
