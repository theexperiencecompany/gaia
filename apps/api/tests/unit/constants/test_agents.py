"""Unit tests for agent tier vocabulary (telemetry attribution keys)."""

from app.constants.agents import COMMS_AGENT_NAME, EXECUTOR_TIER_NAME, NARRATOR_TIER_NAME


class TestTierNames:
    def test_tiers_are_distinct_stable_strings(self) -> None:
        assert COMMS_AGENT_NAME == "comms_agent"
        assert EXECUTOR_TIER_NAME == "executor"
        assert NARRATOR_TIER_NAME == "narrator"
        assert len({COMMS_AGENT_NAME, EXECUTOR_TIER_NAME, NARRATOR_TIER_NAME}) == 3
