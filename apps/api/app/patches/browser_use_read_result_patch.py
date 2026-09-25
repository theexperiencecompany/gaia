"""Show the agent what find_elements and search_page found, not only how many.

Both actions put their matches in extracted_content and a one-line count in
long_term_memory, without include_extracted_content_only_once. Browser-Use's
message manager then gives the model the count alone: the matches reach
neither the read state nor the action results. Measured 2026-09-25 on a
DuckDuckGo results page: find_elements returned the first result's href three
times, and each time the agent was told only "Found 1 element" and asked
again. Flagging the result read-once puts the matches in the next step's read
state, as extract already does.

Pinned to browser-use==0.11.13; the import fails loudly if the method moves.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from browser_use.agent.views import ActionResult
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools

#: The actions whose matches are otherwise summarised away.
_READ_ACTIONS = frozenset({"find_elements", "search_page"})

_original_act: Callable[..., Awaitable[ActionResult]] = Tools.act


async def _act(self: Tools[Any], action: ActionModel, **kwargs: object) -> ActionResult:
    """Run the action; a read action's matches are shown to the model at its next step."""
    # Browser-Use passes everything but action by keyword; a positional call fails loudly here.
    result = await _original_act(self, action=action, **kwargs)
    names = set(action.model_dump(exclude_unset=True))
    if names & _READ_ACTIONS and result.extracted_content and not result.error:
        result.include_extracted_content_only_once = True
    return result


def apply() -> None:
    """Flag find_elements and search_page results read-once."""
    # type.__setattr__ mirrors the stealth patch: an honest rebind that keeps
    # mypy satisfied without an ignore.
    type.__setattr__(Tools, "act", _act)


apply()
