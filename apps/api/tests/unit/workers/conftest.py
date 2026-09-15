"""Shared fixtures for the worker task suites."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _subscription_active_by_default():
    """Defaults every test's user to an active subscription; test_workflow_tasks_paid_only_gate.py overrides to FREE."""
    with patch(
        "app.workers.tasks.workflow_tasks.is_paid",
        AsyncMock(return_value=True),
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
