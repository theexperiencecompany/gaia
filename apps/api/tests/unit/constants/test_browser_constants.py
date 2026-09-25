"""The handoff-action enum against the prompt text the model actually reads.

The preamble tells the model to call the two actions by name. If the enum and
the prose ever disagree, the model is told to call something that isn't
registered — so the prose is pinned to the enum here.
"""

import pytest

from app.constants import browser as browser_constants
from app.constants.browser import BROWSER_TAKEOVER_PREAMBLE, BrowserHandoffAction


@pytest.mark.unit
def test_the_takeover_preamble_names_the_registered_actions() -> None:
    assert BrowserHandoffAction.REQUEST_HUMAN_TAKEOVER.value in BROWSER_TAKEOVER_PREAMBLE
    assert BrowserHandoffAction.SOLVE_CAPTCHA_WITH_HELP.value in BROWSER_TAKEOVER_PREAMBLE


@pytest.mark.unit
def test_handoff_action_members_render_as_their_value_in_prompts() -> None:
    """StrEnum, not (str, Enum): interpolating a member yields the bare action name, never BrowserHandoffAction.REQUEST_HUMAN_TAKEOVER."""
    assert f"{BrowserHandoffAction.REQUEST_HUMAN_TAKEOVER}" == "request_human_takeover"
    assert f"{BrowserHandoffAction.SOLVE_CAPTCHA_WITH_HELP}" == "solve_captcha_with_help"


@pytest.mark.unit
def test_background_job_keys_live_in_the_browser_namespace() -> None:
    """Every job key shares the browser: family, so a namespace flush reaches all of them."""
    prefixes = [
        browser_constants.BROWSER_JOB_LOCK_PREFIX,
        browser_constants.BROWSER_JOB_STATE_PREFIX,
        browser_constants.BROWSER_JOB_EVENTS_PREFIX,
        browser_constants.BROWSER_JOB_JOINER_PREFIX,
        browser_constants.BROWSER_JOB_CANCEL_PREFIX,
    ]
    assert all(prefix.startswith("browser:") for prefix in prefixes)
    assert all(prefix.endswith(":") for prefix in prefixes)
    assert len(set(prefixes)) == len(prefixes)


@pytest.mark.unit
def test_the_slot_lease_outlives_two_missed_heartbeats() -> None:
    """A lease that can lapse between heartbeats wedges the conversation for a run that is still alive."""
    assert (
        browser_constants.BROWSER_JOB_LOCK_TTL_SECONDS
        > 2 * browser_constants.BROWSER_JOB_HEARTBEAT_SECONDS
    )


@pytest.mark.unit
def test_the_joiner_refreshes_faster_than_its_lease_expires() -> None:
    assert (
        browser_constants.BROWSER_JOB_JOINER_REFRESH_SECONDS
        < browser_constants.BROWSER_JOB_JOINER_LEASE_SECONDS
    )
