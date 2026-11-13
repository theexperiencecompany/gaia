"""The drive harness's own rules: a held lock is a failure, a budget is a number."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest
from scripts.playbook_drive.observe import Store
from scripts.playbook_drive.survey import _budget

pytestmark = pytest.mark.unit


class TestWaitForExecutorLock:
    def test_a_lock_still_held_at_the_deadline_is_a_failure_not_a_fire(self) -> None:
        """Firing into a still-held lock is recorded as skipped, not as a scenario result."""
        store = Store.__new__(Store)
        store.db = MagicMock()
        store.db.__getitem__.return_value.find_one.return_value = {"conversation_id": "conv_1"}
        store.redis = MagicMock()
        store.redis.exists.return_value = 1

        with patch("scripts.playbook_drive.observe.time.sleep"), pytest.raises(TimeoutError):
            store.wait_for_executor_lock("wf_1", limit=0)

    def test_a_workflow_that_never_ran_has_no_lock_to_wait_on(self) -> None:
        store = Store.__new__(Store)
        store.db = MagicMock()
        store.db.__getitem__.return_value.find_one.return_value = None
        store.redis = MagicMock()

        store.wait_for_executor_lock("wf_1", limit=0)

        store.redis.exists.assert_not_called()


class TestBudget:
    @pytest.mark.parametrize("text", ["nan", "inf", "-1"])
    def test_a_budget_that_passes_every_comparison_is_refused(self, text: str) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            _budget(text)

    def test_a_plain_amount_is_kept(self) -> None:
        assert _budget("0.5") == 0.5
