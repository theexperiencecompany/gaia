"""The scripted agent's moves, run through the Browser-Use actions a stack's runs use."""

from __future__ import annotations

import time

from app.services.browser.browser_use_tools import GaiaTools
from tests.integration.real.browser._stack.fake_models import WAIT_A_SECOND


async def test_a_scripted_wait_lasts_the_second_a_step_s_patience_counts() -> None:
    """A wait that took no time spent a step's patience before a 1.5 s page timer fired."""
    [(action, params)] = WAIT_A_SECOND.items()
    started = time.monotonic()
    await GaiaTools().registry.execute_action(action, params)
    assert time.monotonic() - started >= 1.0
