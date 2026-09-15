"""Fixtures shared by the API endpoint unit tests."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
async def _bypass_integration_check():
    """Patch check_integration_status so require_integration("gmail") passes."""
    with patch(
        "app.api.v1.dependencies.google_scope_dependencies.check_integration_status",
        new_callable=AsyncMock,
        return_value=True,
    ):
        yield
