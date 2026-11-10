"""Startup indexing of the provider-tool catalog."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tools.tools_warmup import warmup_tools_cache
from app.utils.exceptions import ProviderNotConfiguredError

pytestmark = pytest.mark.unit

_MOD = "app.services.tools.tools_warmup"


def _registry(populate: AsyncMock) -> AsyncMock:
    registry = MagicMock()
    registry.populate_provider_catalog = populate
    return AsyncMock(return_value=registry)


async def test_an_instance_without_composio_skips_the_catalog_without_a_warning() -> None:
    populate = AsyncMock(side_effect=ProviderNotConfiguredError("no Composio key"))

    with (
        patch(f"{_MOD}.get_tool_registry", _registry(populate)),
        patch(f"{_MOD}.log") as log,
    ):
        await warmup_tools_cache()

    log.warning.assert_not_called()
    log.error.assert_not_called()


async def test_a_real_catalog_failure_is_still_reported() -> None:
    populate = AsyncMock(side_effect=RuntimeError("Composio API down"))

    with (
        patch(f"{_MOD}.get_tool_registry", _registry(populate)),
        patch(f"{_MOD}.log") as log,
    ):
        await warmup_tools_cache()

    log.warning.assert_called_once()
