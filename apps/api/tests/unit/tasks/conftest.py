"""Shared fixtures for the scheduled-task suites."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _subscription_active_by_default():
    """Default every reminder fire to a paid user so the paid-only choke point stays out of the way.

    test_reminder_tasks_paid_only_gate.py overrides this to FREE; mirrors tests/unit/workers/conftest.py.
    """
    with patch(
        "app.tasks.reminder_tasks.is_paid",
        AsyncMock(return_value=True),
    ):
        yield
