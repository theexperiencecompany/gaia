"""The handoff-action enum against the prompt text the model actually reads.

The human-checks rules tell the model to call the two actions by name. If the enum and
the prose ever disagree, the model is told to call something that isn't
registered — so the prose is pinned to the enum here.
"""

import pytest

from app.constants import browser as browser_constants
from app.constants.browser import BROWSER_HUMAN_CHECKS, BrowserHandoffAction


@pytest.mark.unit
def test_the_human_checks_name_the_registered_actions() -> None:
    assert BrowserHandoffAction.REQUEST_HUMAN_TAKEOVER.value in BROWSER_HUMAN_CHECKS
    assert BrowserHandoffAction.SOLVE_CAPTCHA_WITH_HELP.value in BROWSER_HUMAN_CHECKS


@pytest.mark.unit
def test_the_slot_lease_outlives_two_missed_heartbeats() -> None:
    """A lease that can lapse between heartbeats wedges the conversation for a run that is still alive."""
    assert (
        browser_constants.BROWSER_JOB_LOCK_TTL_SECONDS
        > 2 * browser_constants.BROWSER_JOB_HEARTBEAT_SECONDS
    )
