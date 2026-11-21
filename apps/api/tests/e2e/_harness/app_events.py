"""The edges an app event crosses before GAIA sees it: Composio's signed webhook and the gate's judge."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import hmac
from itertools import count
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import respx

from app.constants.hil import HIL_JEV_URL
from app.models.trigger_gate_models import GateKind
from app.services.providers.provider_credentials_service import ProviderConfig

#: The secret the journeys sign Composio webhooks with; the fixture installs it as the app's.
WEBHOOK_SECRET = "journeys-webhook-secret"  # pragma: allowlist secret
_SIGNED_AT = "1700000000"


def signed_webhook_headers(body: bytes, webhook_id: str) -> dict[str, str]:
    """Sign a webhook body with the scheme app/utils/webhook_utils.py verifies."""
    signed = webhook_id.encode() + b"." + _SIGNED_AT.encode() + b"." + body
    digest = hmac.new(WEBHOOK_SECRET.encode(), signed, hashlib.sha256).digest()
    return {
        "content-type": "application/json",
        "webhook-id": webhook_id,
        "webhook-timestamp": _SIGNED_AT,
        "webhook-signature": f"v1,{base64.b64encode(digest).decode()}",
    }


class BotOutbox:
    """The message broker the bots consume: records every envelope published to a platform."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def publish_outbound(self, queue_name: str, body: bytes, **_: object) -> None:
        envelope = json.loads(body)
        parts = envelope.get("text_parts") or [envelope["text"]]
        self.sent.append((envelope["platform"], "\n".join(parts)))


def composio_double() -> AsyncMock:
    """Stand in for Composio: every async call succeeds, and each trigger it creates gets an id."""
    service = AsyncMock()
    service.composio = MagicMock()
    created = count(1)
    service.composio.triggers.create.side_effect = lambda **_: SimpleNamespace(
        trigger_id=f"ti_journey_{next(created)}"
    )
    return service


@contextmanager
def gate_judge(*, not_needed: float) -> Iterator[None]:
    """Answer the gate's judge as the model behind it would: P(the event does not need the task)."""
    answer = {
        "answers": {
            "gate": {
                "type": "choice",
                "choice": "not_needed" if not_needed >= 0.5 else "needed",
                "confidence": max(not_needed, 1 - not_needed),
                "probabilities": {"not_needed": not_needed, "needed": 1 - not_needed},
            }
        }
    }
    gate = "app.services.triggers.trigger_gate"
    with (
        respx.mock(assert_all_called=False) as router,
        patch(
            "app.services.hil.jev_client.resolve",
            AsyncMock(return_value=ProviderConfig(api_key="or-key")),  # pragma: allowlist secret
        ),
        patch(f"{gate}.is_trigger_gates_enforced", AsyncMock(return_value=True)),
        patch("app.models.trigger_gate_models.ENFORCED_GATE_KINDS", frozenset(GateKind)),
        # Gmail, asked whether the user wrote in the email's thread: a new email, so no.
        patch(f"{gate}.user_wrote_in_thread", AsyncMock(return_value=False)),
    ):
        router.post(HIL_JEV_URL).mock(return_value=httpx.Response(200, json=answer))
        yield
