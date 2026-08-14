"""Unit tests for ``app.db.rabbitmq`` — publisher bootstrap and lazy lookup."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.lazy_loader import providers
from app.db.rabbitmq import get_rabbitmq_publisher, init_rabbitmq_publisher


@pytest.mark.asyncio
async def test_loader_builds_publisher_from_settings_and_connects() -> None:
    """The registered loader constructs the publisher with RABBITMQ_URL (empty
    string when unset) and connects it before it is handed out."""
    publisher = MagicMock()
    publisher.connect = AsyncMock()
    with (
        patch("app.db.rabbitmq.RabbitMQPublisher", return_value=publisher) as ctor,
        patch("app.db.rabbitmq.settings.RABBITMQ_URL", "amqp://broker/"),
    ):
        # required_keys are captured by @lazy_provider AT IMPORT TIME (so in a
        # hermetic env they are [None] and the loader would refuse to run) —
        # point the registered loader at a concrete key instead.
        loader = init_rabbitmq_publisher()
        loader.required_keys = ["amqp://broker/"]
        result = await loader.aget()

    assert result is publisher
    ctor.assert_called_once_with("amqp://broker/")
    publisher.connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_publisher_raises_when_not_registered() -> None:
    with patch("app.db.rabbitmq.providers.aget", AsyncMock(return_value=None)):
        with pytest.raises(RuntimeError, match="not available"):
            await get_rabbitmq_publisher()
