"""Turn a Browser-Use action into a human-readable caption.

Used as the fallback caption when the model's own ``next_goal`` is absent —
flash mode strips it, or a step produced no goal/thinking text at all — so
the SSE step card (``runner.py``) and the bot's photo caption
(``bot_delivery.py``) describe the same step the same way.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

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


def describe_action(name: str, params: dict[str, Any], target: str | None = None) -> str:
    """A plain-language phrase for one action, using its real target (the URL it
    opens, the text it types, the query it searches) so a caption reads like intent,
    not "Clicking" five times."""
    text = str(params.get("text") or "").strip()
    if name == "navigate":
        # No empty-string fallback: str() of a missing url is "None", which
        # urlparse reports no hostname for — same result, one less dead literal.
        host = urlparse(str(params.get("url"))).hostname or ""
        return f"Opening {host.removeprefix('www.')}" if host else "Opening the page"
    if name in ("search", "search_page"):
        q = str(params.get("query") or params.get("text") or "").strip()
        return f'Searching "{q}"' if q else "Searching"
    if name in ("input", "send_keys"):
        if text and target:
            return f'Typing "{_shorten(text)}" into "{_shorten(target)}"'
        if text:
            return f'Typing "{_shorten(text)}"'
        return f'Typing into "{_shorten(target)}"' if target else "Typing"
    if name == "select_dropdown":
        if text:
            return f'Choosing "{text}"'
        return f'Choosing in "{_shorten(target)}"' if target else "Choosing an option"
    if name == "click":
        if target:
            return f'Clicking "{_shorten(target)}"'
        # A coordinate click resolves no element, so name the point it hit
        # rather than leaving a bare verb with no object at all.
        x, y = params.get("coordinate_x"), params.get("coordinate_y")
        if isinstance(x, int) and isinstance(y, int):
            return f"Clicking at {x}, {y}"
        return "Clicking"
    if name in ("scroll", "scroll_to_text"):
        return "Scrolling"
    if name in ("extract", "read_file", "read_long_content", "find_text", "find_elements"):
        return "Reading the page"
    if name == "upload_file":
        return "Uploading a file"
    if name == "go_back":
        return "Going back"
    if name == "wait":
        return "Waiting for the page"
    if name in ("request_human_takeover", "solve_captcha_with_help"):
        return "Handing this step to you"
    if name == "done":
        return "Wrapping up"
    return name.replace("_", " ")


def caption_from_action_list(actions: list[BrowserAction]) -> str:
    """Same captions, from a step snapshot's structured actions — the params are
    real here, so a caption can name what was opened or typed, not just the verb."""
    return _dedupe_join([describe_action(a.name, a.inputs, a.target) for a in actions])


def _dedupe_join(parts: list[str]) -> str:
    # de-dupe consecutive repeats ("Clicking; Clicking" → "Clicking")
    return ", ".join(dict.fromkeys(p for p in parts if p))
