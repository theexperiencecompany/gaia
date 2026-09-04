"""Shared fixtures for the worker task suites."""

from unittest.mock import AsyncMock, patch

import pytest


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
    ):
        yield
