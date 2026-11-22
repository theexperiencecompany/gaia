"""The edges an app event crosses before GAIA sees it: Composio's signed webhook and the gate's judge."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import hmac
from itertools import count
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import respx

from app.constants.trigger_gates import GateKind
from app.db.repositories.conversation_log import conversation_log_repository
from app.models.conversation_log_models import Notice, Reply
from app.schemas.outbound import OutboundMessageEnvelope
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.hil.jev_client import decisions_url
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
    """The message broker the bots consume: records what each bot sends its user.

    A wake carries no text: the bot follows its conversation past its cursor and sends
    what was logged there, as the bots' follower does.
    """

    def __init__(self, user_id: str) -> None:
        self.sent: list[tuple[str, str]] = []
        self._user_id = user_id
        #: How far each followed conversation has been sent, as the bot's delivered-through cursor.
        self._sent_through: dict[str, int] = {}

    async def publish_outbound(self, queue_name: str, body: bytes, **_: object) -> None:
        envelope = OutboundMessageEnvelope.model_validate_json(body)
        if envelope.follow is None:
            parts = envelope.text_parts or [envelope.text or ""]
            self.sent.append((envelope.platform, "\n".join(parts)))
            return
        conversation_id = envelope.follow.conversation_id
        after = max(envelope.follow.after_seq, self._sent_through.get(conversation_id, 0))
        log = MongoConversationLog(conversation_log_repository, lambda: datetime.now(UTC))
        for logged in await log.read_after(conversation_id, self._user_id, after):
            if isinstance(logged.entry, Notice | Reply) and logged.entry.text:
                self.sent.append((envelope.platform, logged.entry.text))
            self._sent_through[conversation_id] = logged.seq


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
        router.post(decisions_url(None)).mock(return_value=httpx.Response(200, json=answer))
        yield
