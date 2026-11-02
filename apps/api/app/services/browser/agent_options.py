"""What a run's Browser-Use Agent is built with, apart from the live objects it runs on.

The run's contract with Browser-Use: with the user's BROWSER_JEV flag, Jev acts
first, on the part of the task the start page is for, else the start page is
opened (a run resumed on the fallback engine goes on instead), the agent reads pages as text
with whole URLs, and each step gets the run's step budget, which a handoff's
wait is outside of.
"""

from __future__ import annotations

from typing import Any, TypedDict

from browser_use.tools.views import NavigateAction

from app.config.settings import settings
from app.constants.browser import (
    BROWSER_AGENT_FAST_ENGINE_NOTE,
    BROWSER_AGENT_JEV_ROLE,
    BROWSER_AGENT_LLM_TIMEOUT_SECONDS,
    BROWSER_AGENT_ROLE,
    BROWSER_AGENT_URL_QUERY_MAX_CHARS,
    BROWSER_ENGINE_RESUMED_NOTE,
    BROWSER_HUMAN_CHECKS,
    BROWSER_TASK_QUOTE_RULE,
    JEV_FIRST_BURST_DONE_WHEN,
    JEV_FIRST_BURST_GOAL,
)
from app.services.browser.jev.secrets import RunSecrets
from app.services.browser.jev.tool import JEV_ACTION
from app.services.browser.run_contract import BrowserRunConfig

#: Browser-Use's own action that opens an address (registered by function name).
_NAVIGATE_ACTION = "navigate"


class AgentOptions(TypedDict):
    """Browser-Use Agent keyword arguments that carry a decision, not a live object."""

    task: str
    directly_open_url: bool
    initial_actions: list[dict[str, dict[str, Any]]] | None
    sensitive_data: dict[str, str | dict[str, str]] | None
    extend_system_message: str
    use_vision: bool
    use_judge: bool
    flash_mode: bool
    llm_timeout: int
    max_actions_per_step: int
    step_timeout: int
    _url_shortening_limit: int


def agent_options(
    task: str, config: BrowserRunConfig, secrets: RunSecrets, *, resumed: bool, fast_engine: bool
) -> AgentOptions:
    """Return the Agent for task: the start page's first action when there is one, the agent steering after.

    An agent on the fast engine is told so: one that was not believed the page
    it read there was already the full browser, and never moved when the task said to.
    """
    # With no page to reopen, the fallback's session opens on a blank tab.
    moved = BROWSER_ENGINE_RESUMED_NOTE.format(page=config.start_url or "about:blank")
    return AgentOptions(
        # A resumed agent read its own "switch to the full browser" in its history,
        # and asked again: the request it reads every step says the move is done.
        task=task + (secrets.mask(moved) if resumed else "") + BROWSER_TASK_QUOTE_RULE,
        # A resumed run's session already opened its last page; reopening the task's
        # first URL lost that page and the agent's place.
        directly_open_url=not resumed,
        initial_actions=_initial_actions(task, config) if not resumed else None,
        sensitive_data=secrets.sensitive_data() or None,
        extend_system_message=(
            (BROWSER_AGENT_JEV_ROLE if config.jev else BROWSER_AGENT_ROLE)
            + BROWSER_HUMAN_CHECKS
            + (BROWSER_AGENT_FAST_ENGINE_NOTE if fast_engine else "")
        ),
        # The agent reads the page as text; screenshots go to the user's cards, not the model.
        use_vision=False,
        # Browser-Use's post-run judge bills a whole extra call and nothing reads its verdict.
        use_judge=False,
        flash_mode=settings.BROWSER_AGENT_FLASH_MODE,
        llm_timeout=BROWSER_AGENT_LLM_TIMEOUT_SECONDS,
        max_actions_per_step=config.max_actions_per_step,
        step_timeout=config.step_timeout_seconds,
        _url_shortening_limit=BROWSER_AGENT_URL_QUERY_MAX_CHARS,
    )


def _initial_actions(task: str, config: BrowserRunConfig) -> list[dict[str, dict[str, Any]]] | None:
    """Return the start page's first action: Jev's burst there, else opening it; None on a blank tab.

    A burst on the blank tab could only end there, so the agent moves first.
    Opened here, not by Browser-Use's find of a URL in the task: that gives up on two.
    """
    if not config.start_url:
        return None
    if config.jev:
        return [
            {
                JEV_ACTION: {
                    "goal": JEV_FIRST_BURST_GOAL.format(task=task),
                    "done_when": JEV_FIRST_BURST_DONE_WHEN,
                    "start_url": config.start_url,
                }
            }
        ]
    return [{_NAVIGATE_ACTION: NavigateAction(url=config.start_url).model_dump()}]
