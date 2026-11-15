"""Comms must not send GAIA's own held findings back to the executor to be verified."""

import pytest

from app.agents.templates.agent_template import COMMS_PROMPT_BY_SOURCE

RULE = "GAIA'S OWN FINDINGS ARE NOT CHECKED AGAIN"
SECTION = "Results the user has not been told yet"


@pytest.mark.parametrize("source", sorted(COMMS_PROMPT_BY_SOURCE))
def test_every_comms_prompt_forbids_rechecking_findings_gaia_already_reported(source: str) -> None:
    prompt = COMMS_PROMPT_BY_SOURCE[source]

    assert RULE in prompt
    assert SECTION in prompt
