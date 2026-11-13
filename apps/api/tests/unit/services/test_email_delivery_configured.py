"""Email that carries an unsubscribe link needs both a sending key and the secret that signs the link."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.email import service
from app.services.providers.provider_credentials_service import ProviderConfig


@pytest.mark.parametrize(
    ("config", "secret", "expected"),
    [
        (ProviderConfig(api_key="re-stored"), "s3cret", True),
        (ProviderConfig(api_key="re-stored"), "", False),
        (ProviderConfig(api_key=""), "s3cret", False),
        (None, "s3cret", False),
    ],
)
async def test_both_a_key_and_the_unsubscribe_secret_are_needed(
    config: ProviderConfig | None, secret: str, expected: bool
) -> None:
    with (
        patch.object(service, "resolve_provider_config", AsyncMock(return_value=config)),
        patch.object(service.settings, "EMAIL_UNSUBSCRIBE_SECRET", secret),
    ):
        assert await service.email_delivery_configured() is expected
