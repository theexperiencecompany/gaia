"""Turn a Browser-Use action into a human-readable caption.

Used by both the SSE step card (runner.py) and the bot's photo caption
(bot_delivery.py). The model's own next_goal is never used for it: Jev fills
that field with its raw decision label ("CLICK [6] Log In"), not a caption.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from app.constants.browser import BrowserHandoffAction
from app.schemas.browser import BrowserAction

# Actions whose whole meaning is the element they hit — a bare verb reads as
# noise ("Clicking"), the element's text reads as intent ("Clicking Add to cart").
_TARGETED_ACTIONS = {"click", "select_dropdown", "upload_file"}

_TARGET_MAX_CHARS = 40


def _shorten(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _TARGET_MAX_CHARS:
        return collapsed
    return collapsed[: _TARGET_MAX_CHARS - 1].rstrip() + "…"


def _navigate_caption(params: dict[str, Any], _target: str | None) -> str:
    # No empty-string fallback: str() of a missing url is "None", which
    # urlparse reports no hostname for — same result, one less dead literal.
    host = urlparse(str(params.get("url"))).hostname or ""
    return f"Opening {host.removeprefix('www.')}" if host else "Opening the page"


def _search_caption(params: dict[str, Any], _target: str | None) -> str:
    q = str(params.get("query") or params.get("text") or "").strip()
    return f'Searching "{q}"' if q else "Searching"


def _typing_caption(params: dict[str, Any], target: str | None) -> str:
    text = str(params.get("text") or "").strip()
    if text and target:
        return f'Typing "{_shorten(text)}" into "{_shorten(target)}"'
    if text:
        return f'Typing "{_shorten(text)}"'
    return f'Typing into "{_shorten(target)}"' if target else "Typing"


def _select_dropdown_caption(params: dict[str, Any], target: str | None) -> str:
    text = str(params.get("text") or "").strip()
    if text:
        return f'Choosing "{text}"'
    return f'Choosing in "{_shorten(target)}"' if target else "Choosing an option"


def _done_caption(params: dict[str, Any], _target: str | None) -> str:
    # DoneAction.success defaults to True; Jev ends a run it cannot advance
    # with success=False, and "BLOCKED" is not something to show a reader.
    if params.get("success", True):
        return "Finished"
    return "Could not find a way forward on this page"


def _click_caption(params: dict[str, Any], target: str | None) -> str:
    if target:
        return f'Clicking "{_shorten(target)}"'
    # A coordinate click resolves no element, so name the point it hit
    # rather than leaving a bare verb with no object at all.
    x, y = params.get("coordinate_x"), params.get("coordinate_y")
    if isinstance(x, int) and isinstance(y, int):
        return f"Clicking at {x}, {y}"
    return "Clicking"


# Actions whose caption depends on the step's params/target.
_DYNAMIC_CAPTIONS: dict[str, Callable[[dict[str, Any], str | None], str]] = {
    "navigate": _navigate_caption,
    "search": _search_caption,
    "search_page": _search_caption,
    "input": _typing_caption,
    "send_keys": _typing_caption,
    "select_dropdown": _select_dropdown_caption,
    "click": _click_caption,
    "done": _done_caption,
}

# Actions whose caption is the same verb every time, regardless of params.
_STATIC_CAPTIONS: dict[str, str] = {
    "scroll": "Scrolling",
    "scroll_to_text": "Scrolling",
    "extract": "Reading the page",
    "read_file": "Reading the page",
    "read_long_content": "Reading the page",
    "find_text": "Reading the page",
    "find_elements": "Reading the page",
    "upload_file": "Uploading a file",
    "go_back": "Going back",
    "wait": "Waiting for the page",
    BrowserHandoffAction.REQUEST_HUMAN_TAKEOVER: "Handing this step to you",
    BrowserHandoffAction.SOLVE_CAPTCHA_WITH_HELP: "Handing this step to you",
}


def describe_action(name: str, params: dict[str, Any], target: str | None = None) -> str:
    """Return a plain-language phrase for one action, using its real target (the URL it opens, the text it types, the query it searches) so a caption reads like intent, not "Clicking" five times."""
    dynamic = _DYNAMIC_CAPTIONS.get(name)
    if dynamic is not None:
        return dynamic(params, target)
    return _STATIC_CAPTIONS.get(name) or name.replace("_", " ")


def caption_from_action_list(actions: list[BrowserAction]) -> str:
    """Return the same captions, from a step snapshot's structured actions — the params are real here, so a caption can name what was opened or typed, not just the verb."""
    return _dedupe_join([describe_action(a.name, a.inputs, a.target) for a in actions])


def _dedupe_join(parts: list[str]) -> str:
    # de-dupe consecutive repeats ("Clicking; Clicking" → "Clicking")
    return ", ".join(dict.fromkeys(p for p in parts if p))
