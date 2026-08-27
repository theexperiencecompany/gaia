"""Live, opt-in proof that GAIA detects and recovers from a dead Composio connection.

Nothing here is patched. Every test talks to the real Composio API with a real
key, runs real tool executions against a real third-party account, and asserts
against the real ``user_integrations`` document in Mongo. That is the entire
point of this tier: the 1810 classifier, the expiry transition and the webhook
route can all pass a mocked test while being wrong about what Composio actually
sends.

What each test costs
--------------------
- ``test_l1_...``  — one ``connected_accounts.link()`` call (creates a pending
  ``ca_*`` account at Composio) plus one HTTP GET of the Connect Link. Deletes
  the pending account again. Non-destructive.
- ``test_l5_...``  — one real tool execution on the healthy account. Costs
  whatever that tool costs at the provider. Non-destructive. **Run this first**:
  it is the false-positive guard and it needs a live, healthy connection.
- ``test_l2_...``  — **DESTRUCTIVE.** Revokes the user's connected account at
  Composio, then executes a tool against the corpse. The OAuth grant is gone
  afterwards; it deletes the revoked account so the account list stays clean,
  but only a human completing OAuth again (``test_l4_...``) restores service.
- ``test_l3_...``  — **DESTRUCTIVE**, same revocation, and additionally needs a
  publicly reachable GAIA API so Composio can deliver the webhook.
- ``test_l4_...``  — **INTERACTIVE.** Prints a Connect Link and waits for a
  human to complete OAuth in a browser. Run pytest with ``-s`` or you will not
  see the link.

Manual setup
------------
1. ``COMPOSIO_KEY`` — the live key. Declared in ``tests/composio/conftest.py``
   via ``HERMETIC_ALLOW_KEYS`` so the root hermetic fence does not blank it.
   Without it every test here skips.
2. ``USE_REAL_SERVICES=1`` — the root conftest replaces the Mongo client with a
   ``MagicMock`` unless this is set, so every Mongo assertion below would be
   asserting against a mock. L2–L5 skip without it. Mongo and Redis must be the
   same instances the GAIA API/worker use.
3. ``COMPOSIO_LIVE_USER_ID`` — the GAIA user id. It is also the Composio
   ``user_id``: ``connect_account()`` passes the GAIA id straight through and
   the OAuth callback reads the GAIA id back off the connected account.
4. ``COMPOSIO_LIVE_INTEGRATION_ID`` — a Composio-managed integration id from
   ``app/config/oauth_config.py`` (e.g. ``gmail``), already connected for that
   user, i.e. ``user_integrations`` says ``connected``.
5. ``COMPOSIO_LIVE_TOOL_SLUG`` (+ optional ``COMPOSIO_LIVE_TOOL_ARGS`` as a JSON
   object) — a cheap, READ-ONLY tool on that toolkit, e.g.
   ``COMPOSIO_LIVE_TOOL_SLUG=GMAIL_FETCH_EMAILS``
   ``COMPOSIO_LIVE_TOOL_ARGS='{"max_results": 1}'``. Needed by L2 and L5.
6. ``COMPOSIO_LIVE_REVOKE=tool`` (L2) or ``COMPOSIO_LIVE_REVOKE=webhook`` (L3).
   One revocation is available per reconnect, so these are mutually exclusive by
   construction — and because ``pytest-randomly`` shuffles test order, the
   exclusivity has to live in the gates rather than in file order. L5 refuses to
   run in any invocation where a destructive or interactive knob is set.
7. ``COMPOSIO_LIVE_RECONNECT=1`` (L4) — plus a running GAIA API sharing this
   Redis (the OAuth state token) and this Mongo, reachable at ``settings.HOST``
   from the browser that completes the consent.
8. L3 only: the GAIA API must be reachable from the public internet (a tunnel),
   a Composio webhook subscription must point at
   ``<public-host>/api/v1/webhook/composio``, and ``COMPOSIO_WEBHOOK_SECRET``
   must match — otherwise the signature check rejects the delivery.

Suggested sequence, one invocation each (order matters, the runner shuffles)::

    pytest tests/composio/test_connection_expiry_live.py -m composio -k "l1 or l5"
    COMPOSIO_LIVE_REVOKE=tool pytest ... -m composio -k l2
    COMPOSIO_LIVE_RECONNECT=1 pytest ... -m composio -k l4 -s
    COMPOSIO_LIVE_REVOKE=webhook pytest ... -m composio -k l3
    COMPOSIO_LIVE_RECONNECT=1 pytest ... -m composio -k l4 -s

What these tests do NOT exercise
--------------------------------
Tool calls run through a minimal single-node ``StateGraph`` rather than through
the executor agent. That is a real LangGraph runtime — verified to give the tool
a working ``get_stream_writer()`` and to propagate ``metadata.user_id``, the two
things ``_handle_dead_connected_account`` depends on — but it does not exercise
tool selection, the executor's own hooks, or the SSE bridge that carries the
connect card to a browser. L4 drives the real OAuth callback end to end; L3
drives the real webhook endpoint end to end.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import json
import os
import time
from typing import TypedDict

from composio import Composio
import httpx
from langgraph.graph import END, START, StateGraph
import pytest

from app.config.oauth_config import OAuthIntegration, get_integration_by_id
from app.config.settings import settings
from app.constants.integrations import (
    INTEGRATION_STATUS_CONNECTED,
    INTEGRATION_STATUS_EXPIRED,
)
from app.db.repositories.user_integrations import user_integration_repository
from app.models.integration_models import UserIntegrationDocument
from app.services.composio.composio_service import ComposioService
from app.services.composio.langchain_composio_service import StructuredTool
from app.services.integrations.integration_connection_service import (
    connect_composio_integration,
)

# --------------------------------------------------------------------------
# Live configuration — read once at collection time so the skip reasons are
# specific about what is missing.
# --------------------------------------------------------------------------

LIVE_USER_ID = os.environ.get("COMPOSIO_LIVE_USER_ID", "")
LIVE_INTEGRATION_ID = os.environ.get("COMPOSIO_LIVE_INTEGRATION_ID", "")
LIVE_TOOL_SLUG = os.environ.get("COMPOSIO_LIVE_TOOL_SLUG", "")
LIVE_TOOL_ARGS = os.environ.get("COMPOSIO_LIVE_TOOL_ARGS", "{}")
LIVE_REVOKE = os.environ.get("COMPOSIO_LIVE_REVOKE", "")
LIVE_RECONNECT = os.environ.get("COMPOSIO_LIVE_RECONNECT", "")
REAL_SERVICES = os.environ.get("USE_REAL_SERVICES", "0") == "1"

# composio_client 1.39.0 has no typed method for the user-initiated revoke route
# (its own docs mention it: "Revoked via user-initiated revoke endpoint"), so it
# goes through the raw client. The version prefix matches every other
# connected_accounts route in that client. If Composio moves the route, L2/L3
# fail loudly at the revoke step with the API's own response — that is a real
# signal about the SDK, not a test bug.
_REVOKE_PATH = "/api/v3.1/connected_accounts/{nanoid}/revoke"

# The expiry transition is dispatched fire-and-forget from the tool's executor
# thread, so a state assertion has to wait for it. The positive case polls; the
# negative case (L5) has to wait out the same window before it can claim nothing
# happened.
_EXPIRY_TIMEOUT_S = 30.0
_NO_EXPIRY_SETTLE_S = 15.0
_POLL_INTERVAL_S = 1.0

# Composio queues connection-lifecycle webhooks; delivery is not instant.
_WEBHOOK_TIMEOUT_S = 240.0

# A human has to open a browser, log in to the provider and grant consent.
_RECONNECT_TIMEOUT_S = 420.0


def _base_skip_reason() -> str:
    missing = [
        name
        for name, value in (
            ("COMPOSIO_KEY", settings.COMPOSIO_KEY),
            ("COMPOSIO_LIVE_USER_ID", LIVE_USER_ID),
            ("COMPOSIO_LIVE_INTEGRATION_ID", LIVE_INTEGRATION_ID),
        )
        if not value
    ]
    if not missing:
        return ""
    return f"live Composio credentials/config missing: {', '.join(missing)}"


_BASE_REASON = _base_skip_reason()

requires_live_composio = pytest.mark.skipif(bool(_BASE_REASON), reason=_BASE_REASON or "configured")

requires_real_mongo = pytest.mark.skipif(
    not REAL_SERVICES,
    reason=(
        "needs USE_REAL_SERVICES=1: the root conftest swaps the Mongo client for a MagicMock "
        "otherwise, so every user_integrations assertion would be meaningless"
    ),
)

requires_live_tool = pytest.mark.skipif(
    not LIVE_TOOL_SLUG,
    reason="needs COMPOSIO_LIVE_TOOL_SLUG (a cheap read-only tool on the live toolkit)",
)

requires_revoke_via_tool = pytest.mark.skipif(
    LIVE_REVOKE != "tool",
    reason=(
        "DESTRUCTIVE: revokes the live connected account. Set COMPOSIO_LIVE_REVOKE=tool to opt in, "
        "then restore the connection with COMPOSIO_LIVE_RECONNECT=1 -k l4"
    ),
)

requires_revoke_via_webhook = pytest.mark.skipif(
    LIVE_REVOKE != "webhook",
    reason=(
        "DESTRUCTIVE and needs a publicly reachable GAIA API with a Composio webhook subscription "
        "pointing at <public-host>/api/v1/webhook/composio and a matching COMPOSIO_WEBHOOK_SECRET. "
        "Set COMPOSIO_LIVE_REVOKE=webhook to opt in"
    ),
)

requires_interactive_reconnect = pytest.mark.skipif(
    LIVE_RECONNECT != "1",
    reason=(
        "INTERACTIVE: a human must complete OAuth in a browser against a running GAIA API sharing "
        "this Redis and Mongo. Set COMPOSIO_LIVE_RECONNECT=1 and run pytest with -s"
    ),
)

requires_healthy_connection = pytest.mark.skipif(
    bool(LIVE_REVOKE) or LIVE_RECONNECT == "1",
    reason=(
        "the false-positive guard needs a healthy connection, and pytest-randomly shuffles order — "
        "run it in an invocation with no COMPOSIO_LIVE_REVOKE / COMPOSIO_LIVE_RECONNECT set"
    ),
)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def integration() -> OAuthIntegration:
    resolved = get_integration_by_id(LIVE_INTEGRATION_ID)
    if resolved is None or resolved.composio_config is None:
        pytest.fail(
            f"COMPOSIO_LIVE_INTEGRATION_ID={LIVE_INTEGRATION_ID!r} is not a Composio-managed "
            "integration in app/config/oauth_config.py"
        )
    return resolved


@pytest.fixture
def auth_config_id(integration: OAuthIntegration) -> str:
    assert integration.composio_config is not None
    return integration.composio_config.auth_config_id


@pytest.fixture
async def composio_service() -> ComposioService:
    """A real ComposioService, built per test on the test's own event loop.

    ``LangchainProvider`` captures the running loop at construction and later
    dispatches the expiry transition onto it with ``run_coroutine_threadsafe``.
    pytest-asyncio gives every test a fresh loop, so a shared service instance
    would post the transition to a dead one.
    """
    assert settings.COMPOSIO_KEY is not None
    return ComposioService(settings.COMPOSIO_KEY)


@pytest.fixture
def tool_args() -> dict[str, object]:
    parsed = json.loads(LIVE_TOOL_ARGS)
    if not isinstance(parsed, dict):
        pytest.fail(f"COMPOSIO_LIVE_TOOL_ARGS must be a JSON object, got {LIVE_TOOL_ARGS!r}")
    return parsed


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


class _ToolRunState(TypedDict):
    result: object


@dataclass(frozen=True)
class _ToolRun:
    """What a real tool execution produced: its return value and its stream events."""

    result: object
    custom_events: list[dict[str, object]]

    @property
    def connect_card(self) -> dict[str, object] | None:
        """The streamed connect-card payload, the contract the frontend renders.

        Structural on purpose: the agent-facing copy in
        ``request_integration_connection`` is prose and gets reworded, but
        ``integration_id`` / ``expired`` are what the UI actually branches on.
        """
        for event in self.custom_events:
            payload = event.get("integration_connection_required")
            if isinstance(payload, dict):
                return payload
        return None


async def _run_tool_in_graph(
    tool: StructuredTool, args: dict[str, object], user_id: str
) -> _ToolRun:
    """Execute a Composio tool inside a real LangGraph run and capture what it streamed.

    ``_handle_dead_connected_account`` calls ``get_stream_writer()``, which only
    resolves inside a LangGraph runtime, and reads ``user_id`` out of the run's
    config metadata to decide whether to expire anything. Invoking the tool
    directly gives it neither, so the code under test would take a different
    branch than it does in production.
    """
    events: list[dict[str, object]] = []
    result: object = None

    async def call_tool(state: _ToolRunState) -> _ToolRunState:
        # No explicit config: the ambient run config already carries the LangGraph
        # runtime and the metadata below, exactly as a ToolNode invocation does.
        return {"result": await tool.ainvoke(args)}

    builder: StateGraph = StateGraph(_ToolRunState)
    builder.add_node("call_tool", call_tool)
    builder.add_edge(START, "call_tool")
    builder.add_edge("call_tool", END)
    graph = builder.compile()

    async for mode, chunk in graph.astream(
        {"result": None},
        config={"metadata": {"user_id": user_id}},
        stream_mode=["custom", "updates"],
    ):
        if mode == "custom" and isinstance(chunk, dict):
            events.append(chunk)
        elif mode == "updates" and isinstance(chunk, dict) and "call_tool" in chunk:
            result = chunk["call_tool"]["result"]

    return _ToolRun(result=result, custom_events=events)


async def _active_connected_account_id(service: ComposioService, auth_config_id: str) -> str | None:
    accounts = await asyncio.to_thread(
        lambda: service.composio.connected_accounts.list(
            user_ids=[LIVE_USER_ID],
            auth_config_ids=[auth_config_id],
            statuses=["ACTIVE"],
        )
    )
    return next((str(item.id) for item in accounts.items), None)


def _revoke_connected_account(composio: Composio, nanoid: str) -> object:
    """Kill the OAuth grant at Composio. There is no undo — only a fresh consent."""
    return composio.client.post(_REVOKE_PATH.format(nanoid=nanoid), cast_to=object)


async def _poll_record(
    matches: Callable[[UserIntegrationDocument], bool], *, timeout: float
) -> UserIntegrationDocument | None:
    """Poll the live ``user_integrations`` document until it matches, else None."""
    deadline = time.monotonic() + timeout
    while True:
        record = await user_integration_repository.get_for_user(LIVE_USER_ID, LIVE_INTEGRATION_ID)
        if record is not None and matches(record):
            return record
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(_POLL_INTERVAL_S)


async def _require_connected_record() -> UserIntegrationDocument:
    record = await user_integration_repository.get_for_user(LIVE_USER_ID, LIVE_INTEGRATION_ID)
    assert record is not None, (
        f"no user_integrations record for user={LIVE_USER_ID} integration={LIVE_INTEGRATION_ID} — "
        "connect the integration in the app first"
    )
    assert record.status == INTEGRATION_STATUS_CONNECTED, (
        f"expected a healthy connection to start from, found status={record.status!r}. "
        "Reconnect the integration (COMPOSIO_LIVE_RECONNECT=1 -k l4) before running this."
    )
    return record


# --------------------------------------------------------------------------
# L1 — connect
# --------------------------------------------------------------------------


@pytest.mark.composio
@requires_live_composio
async def test_l1_connect_account_mints_a_reachable_connect_link(
    composio_service: ComposioService, integration: OAuthIntegration
) -> None:
    """connect_account() goes through link(), not the retiring initiate() endpoint.

    Proven by the shape of what comes back: link() returns a Composio-hosted
    Connect Link plus the ``ca_*`` nanoid of the account it just staged. The
    retired path would raise ComposioLegacyConnectedAccountsEndpointRetiredError
    instead of returning anything.
    """
    result = await composio_service.connect_account(integration.provider, LIVE_USER_ID)
    connection_id = result["connection_id"]

    try:
        assert result["status"] == "pending"
        assert isinstance(connection_id, str) and connection_id.startswith("ca_"), (
            f"expected a connected-account nanoid, got {connection_id!r}"
        )

        redirect_url = result["redirect_url"]
        assert isinstance(redirect_url, str) and redirect_url.startswith("https://"), (
            f"expected a hosted Connect Link URL, got {redirect_url!r}"
        )

        async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
            response = await client.get(redirect_url)
        assert response.status_code < 400, (
            f"Connect Link {redirect_url} answered {response.status_code} — a user clicking "
            "Connect would land on an error page"
        )
    finally:
        # link() stages a real INITIATED account; leaving one behind per run
        # would slowly fill the user's account list.
        await asyncio.to_thread(composio_service.composio.connected_accounts.delete, connection_id)


# --------------------------------------------------------------------------
# L5 — the false-positive guard (run before anything destructive)
# --------------------------------------------------------------------------


@pytest.mark.composio
@requires_healthy_connection
@requires_live_tool
@requires_real_mongo
@requires_live_composio
async def test_l5_healthy_connected_account_is_left_alone(
    composio_service: ComposioService,
    integration: OAuthIntegration,
    auth_config_id: str,
    tool_args: dict[str, object],
) -> None:
    """A working tool call must not trip the dead-account classifier.

    This is the one that matters. The 1810 markers include loose message
    substrings ("no connected account"), and a false positive here does not
    degrade anything gracefully — it marks a healthy integration expired, pauses
    the user's workflows, and shows them a Reconnect nudge for a connection that
    was never broken.

    What it does not prove: that the tool call *succeeded*. A registered
    after-hook may narrow the Composio envelope to a tool-specific shape, so
    there is no portable ``successful`` field to assert on. The positive signal
    is the pre-flight check that Composio reports the account ACTIVE; the guard
    itself is the three negatives below.
    """
    before = await _require_connected_record()
    active_id = await _active_connected_account_id(composio_service, auth_config_id)
    assert active_id is not None, (
        f"Composio reports no ACTIVE connected account for user={LIVE_USER_ID} "
        f"auth_config={auth_config_id} — this test needs a genuinely healthy connection"
    )

    tool = composio_service.get_tool(LIVE_TOOL_SLUG, user_id=LIVE_USER_ID)
    assert tool is not None, f"Composio has no tool named {LIVE_TOOL_SLUG!r}"

    run = await _run_tool_in_graph(tool, tool_args, LIVE_USER_ID)

    assert run.result is not None, "the tool returned nothing at all"
    assert run.connect_card is None, (
        f"a healthy {integration.name} account was handed a connect card: {run.custom_events}"
    )

    # The expiry is fire-and-forget, so "it did not happen" needs the same window
    # the positive case is allowed to take before it can be claimed.
    await asyncio.sleep(_NO_EXPIRY_SETTLE_S)

    after = await user_integration_repository.get_for_user(LIVE_USER_ID, LIVE_INTEGRATION_ID)
    assert after is not None
    assert after.status == INTEGRATION_STATUS_CONNECTED, (
        f"a healthy tool call expired the integration: {before.status!r} -> {after.status!r}, "
        f"reason={after.expired_reason!r}"
    )
    assert after.expired_at is None
    assert after.expired_reason is None


# --------------------------------------------------------------------------
# L2 — dead account reconciled at tool execution
# --------------------------------------------------------------------------


@pytest.mark.composio
@requires_revoke_via_tool
@requires_live_tool
@requires_real_mongo
@requires_live_composio
async def test_l2_revoked_account_expires_the_integration_at_tool_execution(
    composio_service: ComposioService,
    integration: OAuthIntegration,
    auth_config_id: str,
    tool_args: dict[str, object],
) -> None:
    """Revoke for real, then let a real tool call discover it.

    The returned payload is what pins the tool path specifically: only
    ``_handle_dead_connected_account`` produces the reconnect instruction and
    the connect-card stream event, so neither can be explained by a webhook
    racing this test.
    """
    await _require_connected_record()
    account_id = await _active_connected_account_id(composio_service, auth_config_id)
    assert account_id is not None, (
        f"nothing ACTIVE to revoke for user={LIVE_USER_ID} auth_config={auth_config_id}"
    )

    try:
        await asyncio.to_thread(_revoke_connected_account, composio_service.composio, account_id)

        tool = composio_service.get_tool(LIVE_TOOL_SLUG, user_id=LIVE_USER_ID)
        assert tool is not None, f"Composio has no tool named {LIVE_TOOL_SLUG!r}"

        run = await _run_tool_in_graph(tool, tool_args, LIVE_USER_ID)

        assert isinstance(run.result, dict), (
            f"expected the structured dead-account failure, got {run.result!r}"
        )
        assert run.result["successful"] is False
        assert integration.name in str(run.result["error"]), (
            f"the agent was handed a failure that never names the integration to reconnect: "
            f"{run.result['error']!r}"
        )

        card = run.connect_card
        assert card is not None, (
            f"no connect card was streamed for the dead account: {run.custom_events}"
        )
        assert card["integration_id"] == integration.id
        assert card["expired"] is True, (
            "the card offers a first-time connect; this user HAD this connected and the grant "
            f"died, so the copy and the CTA are both wrong: {card}"
        )

        expired = await _poll_record(
            lambda record: record.status == INTEGRATION_STATUS_EXPIRED,
            timeout=_EXPIRY_TIMEOUT_S,
        )
        assert expired is not None, (
            f"user_integrations never reached 'expired' within {_EXPIRY_TIMEOUT_S}s after the "
            "dead-account tool failure"
        )
        assert expired.expired_at is not None
        assert expired.expired_reason, "the expiry recorded no reason for the user-facing copy"
    finally:
        # The grant is already gone; drop the corpse so the next connect starts
        # from a clean account list. Restoring service needs a human — run
        # COMPOSIO_LIVE_RECONNECT=1 -k l4.
        await asyncio.to_thread(composio_service.composio.connected_accounts.delete, account_id)


# --------------------------------------------------------------------------
# L3 — dead account announced by Composio's webhook
# --------------------------------------------------------------------------


@pytest.mark.composio
@requires_revoke_via_webhook
@requires_real_mongo
@requires_live_composio
async def test_l3_expired_webhook_delivery_expires_the_integration(
    composio_service: ComposioService, auth_config_id: str
) -> None:
    """A real ``composio.connected_account.expired`` delivery drives the expiry.

    No tool runs in this test, so the only thing that can move the record is a
    delivery Composio made to ``/api/v1/webhook/composio`` on the running API —
    signature check, dedupe, envelope validation, terminal-status filter and the
    background transition, all real.

    If the delivery never arrives the test fails rather than passing quietly:
    with the subscription and tunnel declared present (COMPOSIO_LIVE_REVOKE=
    webhook), silence is the bug this test exists to catch.
    """
    await _require_connected_record()
    account_id = await _active_connected_account_id(composio_service, auth_config_id)
    assert account_id is not None, (
        f"nothing ACTIVE to revoke for user={LIVE_USER_ID} auth_config={auth_config_id}"
    )

    try:
        await asyncio.to_thread(_revoke_connected_account, composio_service.composio, account_id)

        expired = await _poll_record(
            lambda record: record.status == INTEGRATION_STATUS_EXPIRED,
            timeout=_WEBHOOK_TIMEOUT_S,
        )
        assert expired is not None, (
            f"no webhook-driven expiry within {_WEBHOOK_TIMEOUT_S}s of revoking {account_id}. "
            "Check: the tunnel is up, the Composio webhook subscription points at "
            "<public-host>/api/v1/webhook/composio, and COMPOSIO_WEBHOOK_SECRET matches the API's"
        )
        assert expired.expired_at is not None
        assert expired.connected_account_id == account_id, (
            "the expiry did not record the account that actually died: "
            f"{expired.connected_account_id!r} != {account_id!r}"
        )
    finally:
        await asyncio.to_thread(composio_service.composio.connected_accounts.delete, account_id)


# --------------------------------------------------------------------------
# L4 — reconnect restores service
# --------------------------------------------------------------------------


@pytest.mark.composio
@requires_interactive_reconnect
@requires_real_mongo
@requires_live_composio
async def test_l4_reconnecting_clears_the_expiry_and_records_the_new_account(
    integration: OAuthIntegration,
) -> None:
    """The human half: real consent, real OAuth callback, real restored record.

    ``status == 'connected'`` is only ever written by the callback path, so the
    assertion cannot be satisfied by the ``created`` upsert this test performs
    when it mints the link.
    """
    record = await user_integration_repository.get_for_user(LIVE_USER_ID, LIVE_INTEGRATION_ID)
    if record is None or record.status != INTEGRATION_STATUS_EXPIRED:
        pytest.skip(
            f"nothing to reconnect: user_integrations status is "
            f"{record.status if record else 'missing'!r}, not 'expired'. Run -k l2 or -k l3 first."
        )

    dead_account_id = record.connected_account_id

    response = await connect_composio_integration(
        user_id=LIVE_USER_ID,
        integration_id=integration.id,
        integration_name=integration.name,
        provider=integration.provider,
        redirect_path="/integrations",
    )
    assert response.redirect_url, f"no Connect Link minted: {response}"

    print(
        f"\n\n>>> Open this in a browser and complete the {integration.name} consent "
        f"(waiting up to {_RECONNECT_TIMEOUT_S:.0f}s):\n{response.redirect_url}\n\n",
        flush=True,
    )

    restored = await _poll_record(
        lambda doc: doc.status == INTEGRATION_STATUS_CONNECTED,
        timeout=_RECONNECT_TIMEOUT_S,
    )
    assert restored is not None, (
        f"the integration never returned to 'connected' within {_RECONNECT_TIMEOUT_S}s. "
        "Check the GAIA API is running, reachable at settings.HOST from the browser, and shares "
        "this Redis (the OAuth state token) and Mongo"
    )
    assert restored.expired_at is None, "reconnecting left a stale expired_at behind"
    assert restored.expired_reason is None, "reconnecting left a stale expired_reason behind"
    assert restored.connected_account_id, "the reconnect recorded no connected account"
    assert restored.connected_account_id != dead_account_id, (
        "the record still points at the dead account "
        f"({dead_account_id!r}) after a successful reconnect"
    )
