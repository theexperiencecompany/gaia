"""The one grammar for a playbook's ``$placeholders``.

The validator (``parser.py``) and the evaluator (``evaluator.py``) both read
placeholders out of a step's arguments, and they have to find exactly the same
ones: a token the validator misses is one the evaluator substitutes unchecked,
and a token the validator checks but the evaluator ignores reaches a tool as
literal text. One scanner, used by both, is what keeps them from disagreeing.

A ``$word`` whose root is not one of the namespaces below is NOT a token: it is
literal text on both sides — the validator does not check it and the evaluator
leaves it untouched. A recorded ``bash`` step legitimately says ``echo $HOME``,
and refusing every ``$identifier`` at write time would refuse that playbook.
``$ask`` is deliberately absent: text a model writes at replay is no longer a
reference into a table but an inline ``{"$ask": ...}`` value standing where the
argument goes, so ``$ask.anything`` in a string is now plain text like any other
unknown root.
"""

from collections.abc import Iterator, Mapping
import re

#: The placeholder namespaces a playbook may address.
PLACEHOLDER_ROOTS: frozenset[str] = frozenset(
    {"now", "today", "user", "trigger", "steps", "last_run"}
)

#: Longest root first so ``last_run`` is never matched as a shorter alternative.
_ROOT_ALTERNATION = "|".join(sorted(PLACEHOLDER_ROOTS, key=len, reverse=True))

#: One token: ``$``, a KNOWN root (ended by a non-identifier character, so
#: ``$nowhere`` is text rather than ``$now`` + ``here``), an optional dotted path,
#: and (meaningful only for the two time roots) an optional signed offset. Used
#: to match, never to build code — the match groups are read as data.
PLACEHOLDER_TOKEN = re.compile(
    rf"\$(?P<root>{_ROOT_ALTERNATION})(?![A-Za-z0-9_])"
    r"(?P<path>(?:\.[A-Za-z0-9_-]+)*)"
    r"(?:\s*(?P<sign>[+-])\s*(?P<amount>\d+)(?P<unit>[wdhms])\b)?"
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
