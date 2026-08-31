"""Shared fixtures for tests/unit/workers/."""

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
