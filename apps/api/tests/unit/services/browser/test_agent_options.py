"""The run's contract with Browser-Use: Jev first on the whole task, whole URLs, text-only steps on the run's budget."""

from __future__ import annotations

import pytest

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
from app.services.browser.agent_options import agent_options, browser_options
from app.services.browser.jev.secrets import RunSecrets
from app.services.browser.jev.tool import JEV_ACTION
from app.services.browser.run_contract import BrowserRunConfig

pytestmark = pytest.mark.unit

CONFIG = BrowserRunConfig(
    max_steps=20,
    max_actions_per_step=3,
    task_timeout_seconds=300,
    step_timeout_seconds=30,
    handoff_timeout_seconds=60,
    stream_screenshots=True,
    solve_captcha=False,
    start_url="https://shop.test/",
)
TASK = "log in with <secret>password</secret> and open the orders page"


def test_jev_acts_first_on_the_whole_task_from_the_start_page() -> None:
    options = agent_options(TASK, CONFIG, RunSecrets({}, []))

    assert options["initial_actions"] == [
        {JEV_ACTION: {"goal": TASK, "start_url": "https://shop.test/"}}
    ]
    assert options["task"] == TASK + BROWSER_TAKEOVER_PREAMBLE
    assert options["extend_system_message"] == BROWSER_AGENT_ROLE


def test_the_runs_secrets_fill_the_agents_placeholders_and_none_means_none() -> None:
    given = agent_options(TASK, CONFIG, RunSecrets({"password": "hunter2"}, ["shop.test"]))
    none = agent_options(TASK, CONFIG, RunSecrets({}, ["shop.test"]))

    assert given["sensitive_data"] == {
        "https://shop.test": {"password": "hunter2"},
        "https://*.shop.test": {"password": "hunter2"},
    }
    assert none["sensitive_data"] is None


def test_the_agent_reads_whole_urls_as_text_with_no_judge() -> None:
    options = agent_options(TASK, CONFIG, RunSecrets({}, []))

    # Regression: Browser-Use shortened query strings past 25 characters (bdc1578d4).
    assert options["_url_shortening_limit"] == BROWSER_AGENT_URL_QUERY_MAX_CHARS
    assert (options["use_vision"], options["use_judge"], options["flash_mode"]) == (
        False,
        False,
        True,
    )


def test_each_step_gets_the_runs_step_budget_and_limits() -> None:
    options = agent_options(TASK, CONFIG, RunSecrets({}, []))

    assert options["step_timeout"] == CONFIG.step_budget_seconds
    assert options["max_actions_per_step"] == 3
    assert options["max_failures"] == BROWSER_AGENT_MAX_FAILURES
    assert options["llm_timeout"] == BROWSER_AGENT_LLM_TIMEOUT_SECONDS


def test_the_browser_renders_the_host_session_at_the_screencast_size() -> None:
    assert browser_options("ws://host.test/devtools/browser/1") == {
        "cdp_url": "ws://host.test/devtools/browser/1",
        "viewport": {"width": BROWSER_VIEWPORT_WIDTH, "height": BROWSER_VIEWPORT_HEIGHT},
        "device_scale_factor": BROWSER_DEVICE_SCALE_FACTOR,
        "no_viewport": False,
    }
