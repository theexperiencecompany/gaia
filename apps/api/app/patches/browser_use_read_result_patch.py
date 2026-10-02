"""Show the agent what its read actions found: the matches, and the page's real title.

find_elements and search_page put their matches in extracted_content and a
one-line count in long_term_memory, without include_extracted_content_only_once.
Browser-Use's message manager then gives the model the count alone (measured
2026-09-25 on DuckDuckGo: three find_elements, each read as "Found 1 element").
Flagging the result read-once puts the matches in the next step's read state.

extract reads the page's markdown, which has no <title>: asked for the title of
example.com, it answered "Not available" and the agent reported the tab label
"example.com" (h_stall, 2026-10-02). Its result now carries document.title.

Pinned to browser-use==0.11.13; the import fails loudly if the method moves.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from browser_use.agent.views import ActionResult
from browser_use.browser.session import BrowserSession
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools

from app.patches.browser_use_page_title_patch import document_title

#: The actions whose matches are otherwise summarised away.
_READ_ACTIONS = frozenset({"find_elements", "search_page"})
#: The action that reads a page's content without its title.
_EXTRACT_ACTION = "extract"

_original_act: Callable[..., Awaitable[ActionResult]] = Tools.act


async def _act(self: Tools[Any], action: ActionModel, **kwargs: object) -> ActionResult:
    """Run the action; a read action's matches are shown to the model at its next step."""
    # Browser-Use passes everything but action by keyword; a positional call fails loudly here.
    result = await _original_act(self, action=action, **kwargs)
    names = set(action.model_dump(exclude_unset=True))
    if names & _READ_ACTIONS and result.extracted_content and not result.error:
        result.include_extracted_content_only_once = True
    if _EXTRACT_ACTION in names and result.extracted_content and not result.error:
        session = kwargs.get("browser_session")
        if isinstance(session, BrowserSession) and (title := await document_title(session)):
            titled = f"<page_title>\n{title}\n</page_title>\n"
            if result.long_term_memory == result.extracted_content:
                result.long_term_memory = titled + result.long_term_memory
            result.extracted_content = titled + result.extracted_content
    return result


def apply() -> None:
    """Flag find_elements and search_page results read-once, and title extract's."""
    # type.__setattr__ mirrors the stealth patch: an honest rebind that keeps
    # mypy satisfied without an ignore.
    type.__setattr__(Tools, "act", _act)


apply()
