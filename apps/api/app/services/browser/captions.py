"""Turn a Browser-Use action into a human-readable caption.

Used by both the SSE step card (runner.py) and the bot's photo caption
(bot_delivery.py). Captions are built from the actions and the elements they
target; the agent's own next_goal names only a step that finishes the run.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from app.constants.browser import (
    BrowserHandoffAction,
)
from app.schemas.browser import BrowserAction


def _shorten(text: str) -> str:
    """Collapse whitespace so multi-line element text reads as one line. Never clips."""
    return " ".join(text.split())


class _ActionParams(BaseModel):
    """The argument fields a caption can name, whatever else the action carried."""

    model_config = ConfigDict(extra="ignore")

    url: str | None = None
    query: str | None = None
    text: str | None = None
    success: bool = True
    coordinate_x: int | None = None
    coordinate_y: int | None = None


def _navigate_caption(params: _ActionParams, _target: str | None) -> str:
    host = urlparse(params.url).hostname if params.url else None
    return f"Opening {host.removeprefix('www.')}" if host else "Opening the page"


def _search_caption(params: _ActionParams, _target: str | None) -> str:
    q = (params.query or params.text or "").strip()
    return f'Searching "{q}"' if q else "Searching"


def _typing_caption(params: _ActionParams, target: str | None) -> str:
    text = (params.text or "").strip()
    if text and target:
        return f'Typing "{_shorten(text)}" into "{_shorten(target)}"'
    if text:
        return f'Typing "{_shorten(text)}"'
    return f'Typing into "{_shorten(target)}"' if target else "Typing"


def _select_dropdown_caption(params: _ActionParams, target: str | None) -> str:
    text = (params.text or "").strip()
    if text:
        return f'Choosing "{text}"'
    return f'Choosing in "{_shorten(target)}"' if target else "Choosing an option"


def _done_caption(params: _ActionParams, _target: str | None) -> str:
    # DoneAction.success defaults to True; the agent sets it False on a run it could not finish.
    if not params.success:
        return "Could not find a way forward on this page"
    # The result message that follows this photo carries the run's answer in
    # full; repeating it here put the whole report on a caption and then again
    # as the next message.
    return "Finished"


def _click_caption(params: _ActionParams, target: str | None) -> str:
    if target:
        return f'Clicking "{_shorten(target)}"'
    # A coordinate click resolves no element, so name the point it hit
    # rather than leaving a bare verb with no object at all.
    x, y = params.coordinate_x, params.coordinate_y
    if x is not None and y is not None:
        return f"Clicking at {x}, {y}"
    return "Clicking"


# Actions whose caption depends on the step's params/target.
_DYNAMIC_CAPTIONS: dict[str, Callable[[_ActionParams, str | None], str]] = {
    "navigate": _navigate_caption,
    "search": _search_caption,
    "search_page": _search_caption,
    "input": _typing_caption,
    "send_keys": _typing_caption,
    "select_dropdown": _select_dropdown_caption,
    "click": _click_caption,
    "done": _done_caption,
}

_SCROLLING = "Scrolling"
_READING = "Reading the page"
_HANDING_OVER = "Handing this step to you"

# Actions whose caption is the same verb every time, regardless of params.
_STATIC_CAPTIONS: dict[str, str] = {
    "scroll": _SCROLLING,
    "scroll_to_text": _SCROLLING,
    "extract": _READING,
    "read_file": _READING,
    "read_long_content": _READING,
    "find_text": _READING,
    "find_elements": _READING,
    "upload_file": "Uploading a file",
    "go_back": "Going back",
    "wait": "Waiting for the page",
    BrowserHandoffAction.REQUEST_HUMAN_TAKEOVER: _HANDING_OVER,
    BrowserHandoffAction.SOLVE_CAPTCHA_WITH_HELP: _HANDING_OVER,
}


def describe_action(name: str, params: Mapping[str, object], target: str | None = None) -> str:
    """Return a plain-language phrase for one action, using its real target (the URL it opens, the text it types, the query it searches) so a caption reads like intent, not "Clicking" five times."""
    dynamic = _DYNAMIC_CAPTIONS.get(name)
    if dynamic is not None:
        return dynamic(_ActionParams.model_validate(params), target)
    return _STATIC_CAPTIONS.get(name) or name.replace("_", " ")


def step_caption(actions: list[BrowserAction], next_goal: str | None) -> str:
    """Return a step's caption; a step that finishes the run is named after the part it finished.

    Only there is the model's next_goal a caption: "Finished" tells the user
    nothing about what the run found.
    """
    finishing = any(
        a.name == "done" and _ActionParams.model_validate(a.inputs).success for a in actions
    )
    if finishing and next_goal and next_goal.strip():
        return _shorten(next_goal)
    return caption_from_action_list(actions)


def caption_from_action_list(actions: list[BrowserAction]) -> str:
    """Return the same captions, from a step snapshot's structured actions — the params are real here, so a caption can name what was opened or typed, not just the verb."""
    return _dedupe_join([describe_action(a.name, a.inputs, a.target) for a in actions])


# How a burst card counts each kind of action ("Typed into 3 fields, clicked 2 times").
_BURST_COUNTS: dict[str, tuple[str, str]] = {
    "input": ("Typed into 1 field", "Typed into {n} fields"),
    "select_dropdown": ("chose 1 option", "chose {n} options"),
    "click": ("clicked once", "clicked {n} times"),
    "send_keys": ("pressed Enter", "pressed Enter {n} times"),
    "scroll": ("scrolled", "scrolled {n} times"),
    "go_back": ("went back", "went back {n} times"),
    "wait": ("waited for the page", "waited for the page"),
}


def burst_caption(actions: list[BrowserAction]) -> str:
    """Return one card's caption for a whole Jev burst: the single action's own caption, else a count per kind."""
    if len(actions) == 1:
        return caption_from_action_list(actions)
    opened = [describe_action(a.name, a.inputs, a.target) for a in actions if a.name == "navigate"]
    counts: dict[str, int] = {}
    for action in actions:
        if action.name in _BURST_COUNTS:
            counts[action.name] = counts.get(action.name, 0) + 1
    parts = [*dict.fromkeys(opened)]
    for name, n in counts.items():
        one, many = _BURST_COUNTS[name]
        parts.append(one if n == 1 else many.format(n=n))
    text = ", ".join(parts) or "Looked at the page"
    return text[0].upper() + text[1:]


def _dedupe_join(parts: list[str]) -> str:
    # de-dupe consecutive repeats ("Clicking; Clicking" → "Clicking")
    return ", ".join(dict.fromkeys(p for p in parts if p))
