"""The one grammar for a playbook's $placeholders.

The validator (parser.py) and the evaluator (evaluator.py) both read
placeholders from a step's arguments and must find exactly the same ones —
one scanner, shared by both, keeps them from disagreeing.

A $word whose root is not a known namespace is literal text on both sides
(e.g. a bash step's echo $HOME), not a token. $ask is deliberately absent:
once a model writes an answer, it's an inline {"$ask": ...} value, not a
reference — so $ask.anything in a string becomes plain text like any other
unknown root.

$item only means something inside a for_each step (the element it's
currently on) and is an error elsewhere; it's a root, not a per-step
convention, so the validator and evaluator can't drift apart on it.
"""

from collections.abc import Iterator, Mapping
import re

#: The placeholder namespaces a playbook may address.
PLACEHOLDER_ROOTS: frozenset[str] = frozenset(
    {"now", "today", "user", "trigger", "steps", "last_run", "item"}
)

#: Longest root first so ``last_run`` is never matched as a shorter alternative.
_ROOT_ALTERNATION = "|".join(sorted(PLACEHOLDER_ROOTS, key=len, reverse=True))

#: One token: ``$``, a KNOWN root (ended by a non-identifier character, so
#: ``$nowhere`` is text rather than ``$now`` + ``here``), an optional dotted
#: path, and an optional signed offset and clock time for the two time roots.
PLACEHOLDER_TOKEN = re.compile(
    rf"\$(?P<root>{_ROOT_ALTERNATION})(?![A-Za-z0-9_])"
    r"(?P<path>(?:\.[A-Za-z0-9_-]+)*)"
    r"(?:\s*(?P<sign>[+-])\s*(?P<amount>\d+)(?P<unit>[wdhms])\b)?"
    r"(?:\s+(?P<clock>[01]\d:[0-5]\d|2[0-3]:[0-5]\d)\b)?"
)


def placeholder_tokens(value: object) -> Iterator[re.Match[str]]:
    """Every placeholder in a value — whole or embedded in text, however deeply nested."""
    if isinstance(value, str):
        yield from PLACEHOLDER_TOKEN.finditer(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from placeholder_tokens(item)
    elif isinstance(value, list):
        for item in value:
            yield from placeholder_tokens(item)
