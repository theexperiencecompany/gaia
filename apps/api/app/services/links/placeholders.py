"""The stand-in a model writes for a heygaia.link, swapped for the real URL only on its way to the user.

A link's URL is a capability once its owner widens it, so it never enters a
tool result, a checkpoint or a trace: the model is handed link_placeholder(...)
and copies it into its reply, and resolve_link_placeholders replaces it with the
target's live link where the reply is delivered. A target with no live link by
then (sharing stopped, taken down) loses the link and keeps its text.
"""

import base64
import binascii
import re

from app.db.repositories.short_links import short_link_repository
from app.models.short_link_models import ShortLinkTargetType
from app.services.links.urls import build_url

PLACEHOLDER_PREFIX = "gaia-link:"
#: How a tool result tells the model to use a placeholder.
LINK_NOTE = (
    "To give the user a link, write its gaia-link: placeholder exactly as given (on its own or as "
    "a markdown link target); it becomes their link when your reply is delivered. It opens for "
    "the user alone until they share it wider from the link's menu."
)
_PLACEHOLDER_CHARS = "A-Za-z0-9_-"
_PLACEHOLDER = re.compile(rf"{PLACEHOLDER_PREFIX}([{_PLACEHOLDER_CHARS}]+)")
# A markdown link around a placeholder: an unresolvable one keeps its label as plain text.
_MARKDOWN_LINK = re.compile(rf"\[([^\]\n]*)\]\({PLACEHOLDER_PREFIX}([{_PLACEHOLDER_CHARS}]+)\)")
_TARGET_SEPARATOR = ":"  # pragma: no mutate — a target type never holds a colon


def link_placeholder(target_type: ShortLinkTargetType, target_id: str) -> str:
    """Return the stand-in for the target's link that a model may carry and repeat."""
    raw = f"{target_type.value}{_TARGET_SEPARATOR}{target_id}".encode()
    return PLACEHOLDER_PREFIX + base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _target(token: str) -> tuple[ShortLinkTargetType, str] | None:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError):
        return None
    type_value, separator, target_id = raw.partition(_TARGET_SEPARATOR)
    if not separator or not target_id or type_value not in ShortLinkTargetType:
        return None
    return ShortLinkTargetType(type_value), target_id


async def _live_url(user_id: str, token: str) -> str | None:
    target = _target(token)
    if target is None:
        return None
    link = await short_link_repository.get_live_for_target(user_id, *target)
    return build_url(link.slug) if link is not None else None


async def resolve_link_placeholders(user_id: str | None, text: str) -> str:
    """Replace each placeholder in text with the live link it stands for, read under user_id.

    A placeholder whose target has no live link is dropped; one written as a
    markdown link leaves its label. Without a user nothing resolves and text is returned as is.
    """
    tokens = set(_PLACEHOLDER.findall(text))
    if user_id is None or not tokens:
        return text
    urls = {token: await _live_url(user_id, token) for token in tokens}
    text = _MARKDOWN_LINK.sub(
        lambda match: f"[{match[1]}]({url})" if (url := urls[match[2]]) else match[1], text
    )
    return _PLACEHOLDER.sub(lambda match: urls[match[1]] or "", text)


# The end of a reply mid-markdown-link: its label, or a target that may still become a placeholder.
_OPEN_LINK_TAIL = re.compile(r"\[[^\]\n]*(?:\](?:\((?P<target>[^)\s]*))?)?\Z")


def _may_become_placeholder(target: str) -> bool:
    return PLACEHOLDER_PREFIX.startswith(target) or _PLACEHOLDER.fullmatch(target) is not None


def _placeholder_tail(text: str) -> int | None:
    start = text.rfind(PLACEHOLDER_PREFIX)
    if start != -1 and _PLACEHOLDER.fullmatch(text, start) is not None:
        return start
    for length in range(min(len(PLACEHOLDER_PREFIX), len(text)), 0, -1):
        if PLACEHOLDER_PREFIX.startswith(text[-length:]):
            return len(text) - length
    return None


def releasable_end(text: str) -> int:
    """Return how much of a reply still streaming can go out without splitting a placeholder.

    Held back: a trailing placeholder (its token may still grow) or the start
    of one, and a trailing markdown link that may still wrap one, so a link
    that cannot resolve is never sent half-built.
    """
    open_link = _OPEN_LINK_TAIL.search(text)
    if open_link is not None and (
        open_link["target"] is None or _may_become_placeholder(open_link["target"])
    ):
        return open_link.start()
    held = _placeholder_tail(text)
    return len(text) if held is None else held
