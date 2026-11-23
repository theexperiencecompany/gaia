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

from pydantic import TypeAdapter, ValidationError

from app.db.repositories.short_links import short_link_repository
from app.models.short_link_models import LinkTarget
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
_TRAILING_PLACEHOLDER = re.compile(rf"{PLACEHOLDER_PREFIX}[{_PLACEHOLDER_CHARS}]+\Z")
# A markdown link around a placeholder: an unresolvable one keeps its label as plain text.
_MARKDOWN_LINK = re.compile(rf"\[([^\]\n]*)\]\({PLACEHOLDER_PREFIX}([{_PLACEHOLDER_CHARS}]+)\)")
_TARGET: TypeAdapter[LinkTarget] = TypeAdapter(LinkTarget)


def link_placeholder(target: LinkTarget) -> str:
    """Return the stand-in for the target's link that a model may carry and repeat."""
    raw = _TARGET.dump_json(target)
    return PLACEHOLDER_PREFIX + base64.urlsafe_b64encode(raw).replace(b"=", b"").decode()


def _target(token: str) -> LinkTarget | None:
    try:
        # The decoder drops padding past what the token needs, so the most it can need will do.
        return _TARGET.validate_json(base64.urlsafe_b64decode(token + "=="))
    except (binascii.Error, ValidationError):
        return None


async def _live_url(user_id: str, token: str) -> str | None:
    target = _target(token)
    if target is None:
        return None
    link = await short_link_repository.get_live_for_target(user_id, target)
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
    trailing = _TRAILING_PLACEHOLDER.search(text)
    if trailing is not None:
        return trailing.start()
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
        open_link.group("target") is None or _may_become_placeholder(open_link.group("target"))
    ):
        return open_link.start()
    held = _placeholder_tail(text)
    return len(text) if held is None else held
