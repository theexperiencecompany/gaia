"""Live connector runners: real E2B sandboxes and the local docker daemon, opt-in only.

Run: bash scripts/dev/infisical-run.sh mise test:one apps/api/tests/connector_runners/<file> -m connector_runners
E2B_API_KEY must survive the hermetic fence, since these tests create real sandboxes;
the GitHub token comes from the host's gh auth token and is only used for read-only calls.
"""

import os
from pathlib import Path

import pytest

os.environ.setdefault("HERMETIC_ALLOW_KEYS", "E2B_API_KEY")

_LIVE_TIER = Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark this tier by path so the default run deselects it."""
    for item in items:
        if _LIVE_TIER in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.connector_runners)
