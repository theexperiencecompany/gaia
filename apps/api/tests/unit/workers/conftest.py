"""Shared fixtures for the worker task suites."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _subscription_active_by_default():
    """Default every test's user to an active (paid) subscription, so the
    paid-only choke point stays out of the way. Its own tests
    (test_workflow_tasks_paid_only_gate.py) override this to FREE."""
    with patch(
        "app.workers.tasks.workflow_tasks.is_subscription_active",
        AsyncMock(return_value=True),
    ):
        yield


@pytest.fixture(autouse=True)
def _no_playbook():
    """Default every workflow fire to "this workflow has no playbook".

    The worker asks the playbook repository before choosing a run path, so
    without this every existing agent-path test would reach Mongo for an answer
    it does not care about. The replay tests
    (``test_workflow_tasks_playbook.py``) patch the same seam with a real
    playbook to take the other branch.
    """
    with patch(
        "app.workers.tasks.workflow_tasks.playbook_repository.get_for_workflow",
        AsyncMock(return_value=None),
    ):
        yield
