"""Shared fixtures for the worker task suites."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.user_models import AuthenticatedUser
from tests.unit.services.conversation.log_helpers import EMPTY


@pytest.fixture(autouse=True)
def _subscription_active_by_default():
    """Defaults every test's user to an active subscription; test_workflow_tasks_paid_only_gate.py overrides to FREE."""
    with patch(
        "app.workers.tasks.workflow_tasks.is_paid",
        AsyncMock(return_value=True),
    ):
        yield


@pytest.fixture(autouse=True)
def _workflow_owners_are_users():
    """Default every workflow fire's owner to a real user; the owner-check tests restore the real check."""
    # create=True: the regression lane runs these suites against a base without the seam.
    with patch(
        "app.workers.tasks.workflow_tasks.require_owner",
        AsyncMock(side_effect=lambda user_id: AuthenticatedUser(user_id=user_id)),
        create=True,
    ):
        yield


@pytest.fixture(autouse=True)
def _no_playbook():
    """Default every workflow fire to "this workflow has no playbook".

    The worker asks the playbook repository before choosing a run path;
    test_workflow_tasks_playbook.py patches the same seam for the other branch.
    """
    with patch(
        "app.workers.tasks.workflow_tasks.playbook_repository.get_for_workflow",
        AsyncMock(return_value=None),
    ):
        yield


@pytest.fixture(autouse=True)
def _free_conversation():
    """Default every workflow fire to "nothing else runs in this conversation".

    A fire is admitted to its workflow's conversation before it spends anything, so
    without this every existing test would reach Mongo for the conversation and its
    log, and Redis for the admission key. The overlap tests patch the same seams to
    say it is busy.
    """
    idle_log = MagicMock(state=AsyncMock(return_value=EMPTY))
    admission = MagicMock(
        set=AsyncMock(return_value=True), get=AsyncMock(return_value=None), delete=AsyncMock()
    )
    with (
        patch(
            "app.workers.tasks.workflow_tasks.get_or_create_workflow_conversation",
            AsyncMock(return_value="conv_1"),
        ),
        patch("app.workers.tasks.workflow_tasks.redis_cache", MagicMock(client=admission)),
        patch(
            "app.workers.tasks.workflow_tasks.runtime_ports",
            MagicMock(return_value=MagicMock(log=idle_log)),
        ),
        patch("app.workers.tasks.workflow_tasks.keep_alive", AsyncMock(return_value=MagicMock())),
    ):
        yield
