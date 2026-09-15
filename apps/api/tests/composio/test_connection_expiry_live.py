"""Live, opt-in proof that GAIA detects and recovers from a dead Composio connection.

Nothing is patched: real Composio API, real third-party account, real user_integrations in Mongo.
l1 creates then deletes a pending account; l5 runs one read-only tool (false-positive guard, run
first, needs a healthy connection); l2 (tool) and l3 (webhook) are DESTRUCTIVE revocations; l4 is
INTERACTIVE OAuth (run with -s). Needs COMPOSIO_KEY, USE_REAL_SERVICES=1 (else Mongo is a
MagicMock; Mongo/Redis must be the API's), COMPOSIO_LIVE_USER_ID, COMPOSIO_LIVE_INTEGRATION_ID
(already connected) and COMPOSIO_LIVE_TOOL_SLUG[/_ARGS] (read-only). COMPOSIO_LIVE_REVOKE=tool|webhook
and COMPOSIO_LIVE_RECONNECT=1 arm l2/l3/l4. One revocation per reconnect and pytest-randomly
shuffles, so exclusivity lives in the gates; l5 refuses to run with any knob set. l3 needs a public
GAIA API, a Composio webhook to /api/v1/webhook/composio and a matching COMPOSIO_WEBHOOK_SECRET;
l4 needs a GAIA API sharing this Redis/Mongo at settings.HOST. One invocation each, in order:
-k "l1 or l5"; REVOKE=tool -k l2; RECONNECT=1 -k l4 -s; REVOKE=webhook -k l3; RECONNECT=1 -k l4 -s.
Tools run in a one-node StateGraph, not the executor: tool selection, executor hooks and the SSE
bridge are not exercised.
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

# Live configuration — read once at collection time so the skip reasons are
# specific about what is missing.

LIVE_USER_ID = os.environ.get("COMPOSIO_LIVE_USER_ID", "")
LIVE_INTEGRATION_ID = os.environ.get("COMPOSIO_LIVE_INTEGRATION_ID", "")
LIVE_TOOL_SLUG = os.environ.get("COMPOSIO_LIVE_TOOL_SLUG", "")
LIVE_TOOL_ARGS = os.environ.get("COMPOSIO_LIVE_TOOL_ARGS", "{}")
LIVE_REVOKE = os.environ.get("COMPOSIO_LIVE_REVOKE", "")
LIVE_RECONNECT = os.environ.get("COMPOSIO_LIVE_RECONNECT", "")
REAL_SERVICES = os.environ.get("USE_REAL_SERVICES", "0") == "1"

# composio_client 1.39.0 has no typed method for the user-initiated revoke
# route, so it goes through the raw client; if Composio moves the route,
# L2/L3 fail loudly at the revoke step with the API's own response.
_REVOKE_PATH = "/api/v3.1/connected_accounts/{nanoid}/revoke"

# The expiry transition is dispatched fire-and-forget from the tool's
# executor thread, so a state assertion has to poll; L5 waits out the same
# window before it can claim nothing happened.
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
    """Build a real ComposioService, per test, on the test's own event loop.

    LangchainProvider captures the running loop at construction and later
    dispatches the expiry transition onto it; pytest-asyncio gives every
    test a fresh loop, so a shared instance would post to a dead one.
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
        request_integration_connection is prose and gets reworded, but
        integration_id / expired are what the UI actually branches on.
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

    _handle_dead_connected_account calls get_stream_writer() (resolves only
    inside a LangGraph runtime) and reads user_id from the run's config
    metadata; invoking the tool directly gives it neither.
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
    """Poll the live user_integrations document until it matches, else None."""
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
    """connect_account() goes through link(), not the retiring initiate() endpoint (which raises ComposioLegacyConnectedAccountsEndpointRetiredError)."""
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
    """A false positive here wrongly expires a healthy integration and pauses the user's workflows; does not prove the tool call itself succeeded."""
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
    """Revoke for real; only _handle_dead_connected_account produces the reconnect instruction and connect-card event, so a racing webhook can't explain it."""
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
    """No tool runs here — only a real webhook delivery to /api/v1/webhook/composio can move the record, and a silent non-delivery fails the test rather than passing quietly."""
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
    """The status "connected" is only ever written by the callback path, not by the created upsert this test performs when it mints the link."""
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
