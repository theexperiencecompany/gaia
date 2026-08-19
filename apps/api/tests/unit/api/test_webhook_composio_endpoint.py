"""Tests for app/api/v1/endpoints/webhook_composio.py"""

from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

ENDPOINT = "/api/v1/webhook/composio"
MODULE = "app.api.v1.endpoints.webhook_composio"


@pytest.fixture
def _accepted_delivery():
    """Signature verified and the dedupe key unclaimed, so the body reaches the router."""
    redis = MagicMock()
    redis.client.set = AsyncMock(return_value=True)
    with (
        patch(f"{MODULE}.verify_composio_webhook_signature", AsyncMock()),
        patch(f"{MODULE}.redis_cache", redis),
    ):
        yield


@pytest.mark.usefixtures("_accepted_delivery")
class TestMalformedBody:
    """Composio redelivers anything that is not a 2xx, and the dedupe key is
    claimed before the body is read — so a 500 on a body Composio can never
    re-send correctly becomes an infinite redelivery loop whose retries are
    then swallowed as duplicates."""

    @pytest.mark.regression
    @pytest.mark.parametrize(
        ("raw_body", "label"),
        [(b"[]", "array"), (b'"nope"', "string"), (b"7", "number"), (b"null", "null")],
    )
    async def test_a_json_body_that_is_not_an_object_is_acked_not_raised(
        self, unauthed_client: AsyncClient, raw_body: bytes, label: str
    ) -> None:
        response = await unauthed_client.post(
            ENDPOINT,
            content=raw_body,
            headers={"content-type": "application/json", "webhook-id": f"conn-nonobject-{label}"},
        )

        assert response.status_code < 500, "A malformed body must be acked or refused, never 500'd"
        assert response.json()["message"] == "Webhook body not understood"
