"""A direct dev run that parks on a HIL approval must fail loud, not answer empty.

When a run pauses, ``SubagentOutcome.text`` is ``""`` — returning it would present
an empty string as the agent's answer. A direct run has no approval channel to
resume on, so the only honest outcome is an error naming that.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.subagents.subagent_runner import SubagentOutcome
from app.services.dev_agent_service import _dev_base_configurable, _reject_pause
from app.utils.errors import AppError

MODULE = "app.services.dev_agent_service"


def test_a_paused_outcome_raises_conflict_instead_of_returning_empty_text() -> None:
    paused = SubagentOutcome(text="", interrupt={"type": "hil_approval", "approval_id": "a1"})

    with pytest.raises(AppError) as excinfo:
        _reject_pause(paused, "executor_agent")

    assert excinfo.value.status_code == 409


def test_a_finished_outcome_passes_through() -> None:
    assert _reject_pause(SubagentOutcome(text="done"), "executor_agent") is None


async def test_the_dev_users_onboarding_data_reaches_the_configurable() -> None:
    """``_dev_base_configurable`` is the root of both direct-run paths
    (``run_executor_direct`` / ``run_subagent_direct``) — it already has the
    full ``UserDocument`` from ``require_dev_user`` in hand, so it must thread
    ``onboarding`` into ``build_agent_config`` the same way comms does, not
    leave a direct run blind to preferences a real chat turn would carry."""
    user_doc = MagicMock(
        id="dev-user-1",
        email="dev@gaia.local",
        name="Dev User",
        onboarding={
            "preferences": {"profession": "engineer"},
            "writing_style": {"summary": "terse"},
        },
    )
    with patch(f"{MODULE}.require_dev_user", AsyncMock(return_value=user_doc)):
        configurable, user_id, _ = await _dev_base_configurable("dev@gaia.local", None, "executor")

    assert user_id == "dev-user-1"
    assert configurable["user_preferences"] == {"profession": "engineer"}
    assert configurable["writing_style"] == {"summary": "terse"}
