"""Shared fixtures for the worker task suites."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.user_models import AuthenticatedUser


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
    """Default every workflow fire to "nobody else holds this conversation".

    A fire claims its workflow's conversation before it spends anything, so
    without this every existing test would reach Mongo for the conversation and
    Redis for the lock. The overlap tests patch the same seams to say it is
    held.
    """
    with (
        patch(
            "app.workers.tasks.workflow_tasks.get_or_create_workflow_conversation",
            AsyncMock(return_value="conv_1"),
        ),
        patch("app.workers.tasks.workflow_tasks.try_acquire_lock", AsyncMock(return_value=True)),
        patch("app.workers.tasks.workflow_tasks.release_lock_if_owned", AsyncMock()),
        patch("app.workers.tasks.workflow_tasks.get_lock_holder", AsyncMock(return_value=None)),
        patch("app.workers.tasks.workflow_tasks.keep_alive", AsyncMock(return_value=MagicMock())),
    ):
        yield
