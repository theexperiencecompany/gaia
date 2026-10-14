"""Importing app.patches installs the one Browser-Use patch left: each run's own event lock."""

import bubus.service as bubus_service
import pytest

# Importing a patch module imports app.patches first, which applies every patch.
from app.patches import browser_use_run_lock_patch

pytestmark = pytest.mark.unit


def test_the_run_lock_patch_is_installed() -> None:
    assert bubus_service._get_global_lock is browser_use_run_lock_patch._get_run_lock
