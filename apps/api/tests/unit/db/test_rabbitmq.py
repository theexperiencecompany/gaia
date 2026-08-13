"""Unit tests for ``app.db.rabbitmq`` — publisher bootstrap and lazy lookup."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.rabbitmq import get_rabbitmq_publisher, init_rabbitmq_publisher, providers


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
        # Registration happens in the app lifespan; in the unit tier we call the
        # decorated function ourselves, then the first aget runs the loader.
        init_rabbitmq_publisher()
        result = await providers.aget("rabbitmq_publisher")

    assert result is publisher
    ctor.assert_called_once_with("amqp://broker/")
    publisher.connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_publisher_raises_when_not_registered() -> None:
    with patch("app.db.rabbitmq.providers.aget", AsyncMock(return_value=None)):
        with pytest.raises(RuntimeError, match="not available"):
            await get_rabbitmq_publisher()
