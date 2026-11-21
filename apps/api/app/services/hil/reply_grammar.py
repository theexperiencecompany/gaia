"""Read a bot reply that is in the approval prompt's own grammar, with no model.

The prompt (libs/shared/ts/src/bots/conversation/approval-prompt.ts) offers "yes" or
"no" for one approval, and "yes" to all, "no" to all or "yes 1 and 3" for several.
A reply that is exactly that is decided here; anything else is the classifier's.
"""

from collections.abc import Collection
from dataclasses import dataclass
import re

from app.constants.hil import HIL_PLAIN_REPLY_WORDS, ApprovalDecision

_PLAIN_REPLY = re.compile(r"(?P<word>[a-z]+)(?P<items>(?:\s*(?:,|&|\band\b)?\s*\d+)*)")
_ITEM = re.compile(r"\d+")
_DECORATION = "*_~`.! "


@dataclass(frozen=True)
class PlainReply:
    """One decision, for the approval numbers it names or, when none, for every one."""

    decision: ApprovalDecision
    items: tuple[int, ...] = ()


def read_plain_reply(message: str, numbers: Collection[int]) -> PlainReply | None:
    """Return the reply's decision when it is the prompt's grammar over the open approvals' numbers, else None."""
    match = _PLAIN_REPLY.fullmatch(message.strip(_DECORATION).lower())
    if match is None or match.group("word") not in HIL_PLAIN_REPLY_WORDS:
        return None
    items = tuple(sorted({int(item) for item in _ITEM.findall(match.group("items"))}))
    if any(item not in numbers for item in items):
        return None
    return PlainReply(HIL_PLAIN_REPLY_WORDS[match.group("word")], items)
