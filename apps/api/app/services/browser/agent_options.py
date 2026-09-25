"""What a run's Browser-Use Browser and Agent are built with, apart from the live objects they run on.

The run's contract with Browser-Use: Jev acts first on the whole task, the agent
reads pages as text with whole URLs, and each step gets the run's step budget.
"""

from __future__ import annotations

from typing import Any, TypedDict

from app.constants.browser import (
    BROWSER_AGENT_LLM_TIMEOUT_SECONDS,
    BROWSER_AGENT_MAX_FAILURES,
    BROWSER_AGENT_ROLE,
    BROWSER_AGENT_URL_QUERY_MAX_CHARS,
    BROWSER_DEVICE_SCALE_FACTOR,
    BROWSER_TAKEOVER_PREAMBLE,
    BROWSER_VIEWPORT_HEIGHT,
    BROWSER_VIEWPORT_WIDTH,
)
from app.services.browser.jev.secrets import RunSecrets
from app.services.browser.jev.tool import JEV_ACTION
from app.services.browser.run_contract import BrowserRunConfig


class BrowserOptions(TypedDict):
    """Browser-Use Browser keyword arguments for a session on the host."""

    cdp_url: str
    viewport: dict[str, int]
    device_scale_factor: int
    #: Browser-Use sizes the page to the viewport, the size the host screencasts.
    no_viewport: bool


class AgentOptions(TypedDict):
    """Browser-Use Agent keyword arguments that carry a decision, not a live object."""

    task: str
    initial_actions: list[dict[str, dict[str, Any]]]
    sensitive_data: dict[str, str | dict[str, str]] | None
    extend_system_message: str
    use_vision: bool
    use_judge: bool
    flash_mode: bool
    max_failures: int
    llm_timeout: int
    max_actions_per_step: int
    step_timeout: int
    _url_shortening_limit: int


def browser_options(cdp_url: str) -> BrowserOptions:
    """Return the Browser for the host session at cdp_url, at the size the host screencasts."""
    return BrowserOptions(
        cdp_url=cdp_url,
        viewport={"width": BROWSER_VIEWPORT_WIDTH, "height": BROWSER_VIEWPORT_HEIGHT},
        device_scale_factor=BROWSER_DEVICE_SCALE_FACTOR,
        no_viewport=False,
    )


def agent_options(task: str, config: BrowserRunConfig, secrets: RunSecrets) -> AgentOptions:
    """Return the Agent for task: Jev's burst on the whole task first, the agent steering after."""
    return AgentOptions(
        task=task + BROWSER_TAKEOVER_PREAMBLE,
        initial_actions=[{JEV_ACTION: {"goal": task, "start_url": config.start_url}}],
        sensitive_data=secrets.sensitive_data() or None,
        extend_system_message=BROWSER_AGENT_ROLE,
        # The agent reads the page as text; screenshots go to the user's cards, not the model.
        use_vision=False,
        # Browser-Use's post-run judge bills a whole extra call and nothing reads its verdict.
        use_judge=False,
        flash_mode=True,
        max_failures=BROWSER_AGENT_MAX_FAILURES,
        llm_timeout=BROWSER_AGENT_LLM_TIMEOUT_SECONDS,
        max_actions_per_step=config.max_actions_per_step,
        step_timeout=config.step_budget_seconds,
        _url_shortening_limit=BROWSER_AGENT_URL_QUERY_MAX_CHARS,
    )
