"""The voice pass's link tokens: a markdown link on a phrase whose address is link:N.

The facts hand the model "(link:N)" to put right after its phrase in brackets, the one
link shape models already write; anything else that mentions a token is malformed.
"""

from collections.abc import Collection
import re

LINK_TOKEN_RE = re.compile(r"\[([^\[\]\n]+)\]\(link:(\d+)\)")
# What is left of a token the model mangled once every well-formed one is unlinked.
_TOKEN_RESIDUE_RE = re.compile(r"\S*(?:\(link:|\blink:\s*\d|\[\[|\]\])\S*")


def link_token(index: int) -> str:
    """Return the address the facts show for one linkable item."""
    return f"(link:{index})"


def link_token_problems(message: str, link_ids: Collection[int]) -> list[str]:
    """Name every link token in the message that is malformed or points at no linkable item."""
    problems = [
        f"the message links {match.group(0)!r}, but no fact carries link:{match.group(2)}; "
        "link only an item whose fact has a link"
        for match in LINK_TOKEN_RE.finditer(message)
        if int(match.group(2)) not in link_ids
    ]
    problems += [
        f"the message has a malformed link {match.group(0)!r}; write a linked phrase "
        "exactly as [the phrase](link:N) and nothing else around it"
        for match in _TOKEN_RESIDUE_RE.finditer(LINK_TOKEN_RE.sub(r"\1", message))
    ]
    return problems
