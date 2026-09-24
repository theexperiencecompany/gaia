"""Turn a Browser-Use action into a human-readable caption.

Used by both the SSE step card (runner.py) and the bot's photo caption
(bot_delivery.py). The model's own next_goal is used only for a step that
finishes the run: everywhere else Jev fills that field with its raw decision
label ("CLICK [6] Log In"), not a caption.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from app.constants.browser import (
    BROWSER_AGENT_GUIDANCE_CAPTION,
    BrowserHandoffAction,
)
from app.schemas.browser import BrowserAction

# Actions whose whole meaning is the element they hit — a bare verb reads as
# noise ("Clicking"), the element's text reads as intent ("Clicking Add to cart").
_TARGETED_ACTIONS = {"click", "select_dropdown", "upload_file"}


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
    # DoneAction.success defaults to True; Jev ends a run it cannot advance
    # with success=False, and "BLOCKED" is not something to show a reader.
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
    # The agent round trip is not the user's business; they see only that the
    # run is looking for another route.
    BrowserHandoffAction.REQUEST_AGENT_GUIDANCE: BROWSER_AGENT_GUIDANCE_CAPTION,
}


def describe_action(name: str, params: Mapping[str, object], target: str | None = None) -> str:
    """Return a plain-language phrase for one action, using its real target (the URL it opens, the text it types, the query it searches) so a caption reads like intent, not "Clicking" five times."""
    dynamic = _DYNAMIC_CAPTIONS.get(name)
    if dynamic is not None:
        return dynamic(_ActionParams.model_validate(params), target)
    return _STATIC_CAPTIONS.get(name) or name.replace("_", " ")


def step_caption(actions: list[BrowserAction], next_goal: str | None) -> str:
    """Return a step's caption; a step that finishes the run is named after the part it finished.

    Only there is the model's next_goal a caption: Jev puts the plan part's goal
    in it, where "Finished" told the user nothing about the run's one step.
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


def _dedupe_join(parts: list[str]) -> str:
    # de-dupe consecutive repeats ("Clicking; Clicking" → "Clicking")
    return ", ".join(dict.fromkeys(p for p in parts if p))
