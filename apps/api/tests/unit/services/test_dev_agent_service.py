"""A direct dev run that parks on a HIL approval must fail loud, not answer empty.

When a run pauses, ``SubagentOutcome.text`` is ``""`` — returning it would present
an empty string as the agent's answer. A direct run has no approval channel to
resume on, so the only honest outcome is an error naming that.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.subagents.subagent_runner import SubagentOutcome
from app.agents.llm.lane import AgentRole
from app.services.dev_agent_service import _dev_base_configurable, _reject_pause
from app.utils.errors import AppError

_MOD = "app.services.dev_agent_service"


def test_a_paused_outcome_raises_conflict_instead_of_returning_empty_text() -> None:
    paused = SubagentOutcome(text="", interrupt={"type": "hil_approval", "approval_id": "a1"})

    with pytest.raises(AppError) as excinfo:
        _reject_pause(paused, "executor_agent")

    assert excinfo.value.status_code == 409


def test_a_finished_outcome_passes_through() -> None:
    assert _reject_pause(SubagentOutcome(text="done"), "executor_agent") is None


class TestTheParentConfigurableADirectRunBuilds:
    """A direct run is top-level, so it has to resolve its own lane.

    It resolved none at all before, which is why the dev harness quietly ran a
    different model than real chat — the one thing the harness exists to be
    faithful about.
    """

    def _dev_user(self) -> MagicMock:
        user = MagicMock()
        user.id = "u1"
        user.email = "dev@gaia.local"
        user.name = "Dev"
        return user

    async def _build(self, conversation_id: str | None) -> tuple[AsyncMock, str, str]:
        build_config = AsyncMock(return_value={"configurable": {"thread_id": "t"}})
        with (
            patch(
                f"{_MOD}.require_dev_user", new_callable=AsyncMock, return_value=self._dev_user()
            ),
            patch(f"{_MOD}.build_agent_config", build_config),
        ):
            _, user_id, cid = await _dev_base_configurable(
                "dev@gaia.local", conversation_id, "executor_agent"
            )
        return build_config, user_id, cid

    async def test_it_resolves_a_lane_as_the_executor_tier(self) -> None:
        build_config, _, cid = await self._build("conv-1")

        assert build_config.call_args.kwargs == {
            "conversation_id": cid,
            "user": {"user_id": "u1", "email": "dev@gaia.local", "name": "Dev"},
            "agent_name": "executor_agent",
            "role": AgentRole.EXECUTOR,
        }

    async def test_a_passed_conversation_id_is_reused_so_turns_share_a_thread(self) -> None:
        _, _, cid = await self._build("conv-1")

        assert cid == "conv-1"

    async def test_a_missing_conversation_id_is_minted(self) -> None:
        _, _, cid = await self._build(None)

        assert cid and cid != "conv-1"
