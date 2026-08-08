"""Per-suite dev identities for the live chat-stream transport.

``quality.ChatStreamTransport`` is the harness's one SSE transport over
``POST /api/v1/chat-stream`` — the exact wire the web frontend consumes. It pins
its dev user to the quality suite's email, which is right for one suite and wrong
for three: the comms agent runs a memory node on every turn, so suites sharing an
identity would recall each other's cases across runs, and a safety suite's
injection payloads are the last thing a comms case should have in its context.

:class:`SuiteChatTransport` binds that same transport to a suite's own dev user.
It overrides only the identity step; every byte of frame parsing, multi-turn
threading and token estimation stays in the one implementation.

The HIL suite does NOT use this: an approval flow is stream → decide → resume →
re-read, which is a different shape of run, not a different user (see hil.py).
"""

from __future__ import annotations

import httpx

from scripts.evals.core.providers import ProviderConfig
from scripts.evals.core.types import ProviderError
from scripts.evals.suites.quality import DEV_USERS_URL, ChatStreamTransport


class SuiteChatTransport(ChatStreamTransport):
    """The live chat-stream transport, minting and using ``email`` as its user."""

    def __init__(self, email: str) -> None:
        super().__init__()
        self._suite_email = email

    async def _ensure_user(self, client: httpx.AsyncClient, provider: ProviderConfig) -> None:
        if self._email:
            return
        resp = await client.post(DEV_USERS_URL, json={"email": self._suite_email})
        if resp.status_code not in (200, 201):
            raise ProviderError(
                provider.name,
                f"dev users endpoint failed for {self._suite_email}: "
                f"HTTP {resp.status_code}: {(resp.text or '')[:200]}",
            )
        self._email = self._suite_email
