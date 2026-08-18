"""Composio webhook signature verification — the endpoint's only auth."""

import base64
import hashlib
import hmac
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
import pytest

from app.utils.webhook_utils import verify_composio_webhook_signature

SECRET = "whsec_test"


def _request(body: bytes, secret: str | None = SECRET) -> MagicMock:
    signed = b"wh-1" + b"." + b"1700000000" + b"." + body
    sig = base64.b64encode(hmac.new((secret or "").encode(), signed, hashlib.sha256).digest())
    request = MagicMock()
    request.headers = {
        "webhook-id": "wh-1",
        "webhook-timestamp": "1700000000",
        "webhook-signature": "v1," + sig.decode(),
    }

    async def _body() -> bytes:
        return body

    request.body = _body
    return request


async def test_a_valid_signature_passes() -> None:
    with patch("app.utils.webhook_utils.settings") as settings:
        settings.COMPOSIO_WEBHOOK_SECRET = SECRET
        body, webhook_id = await verify_composio_webhook_signature(_request(b"{}"))

    assert body == b"{}"
    assert webhook_id == "wh-1"


async def test_a_missing_secret_fails_loud_not_open() -> None:
    """An empty HMAC key is one anyone can compute: with the secret unset,
    a forged empty-key signature must NOT authenticate."""
    with patch("app.utils.webhook_utils.settings") as settings:
        settings.COMPOSIO_WEBHOOK_SECRET = None
        with pytest.raises(HTTPException) as excinfo:
            await verify_composio_webhook_signature(_request(b"{}", secret=None))

    assert excinfo.value.status_code == 500
    # Exact text, not a substring: this 500 is the only thing that tells the
    # operator WHICH secret is missing, and a mangled or blank detail leaves
    # them with an unexplained 500 on the webhook endpoint.
    assert excinfo.value.detail == "COMPOSIO_WEBHOOK_SECRET is not configured"


async def test_a_wrong_signature_is_rejected() -> None:
    with patch("app.utils.webhook_utils.settings") as settings:
        settings.COMPOSIO_WEBHOOK_SECRET = "a-different-secret"
        with pytest.raises(HTTPException) as excinfo:
            await verify_composio_webhook_signature(_request(b"{}"))

    assert excinfo.value.status_code == 401
