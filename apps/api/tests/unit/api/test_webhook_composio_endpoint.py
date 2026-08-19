"""Tests for app/api/v1/endpoints/webhook_composio.py"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

ENDPOINT = "/api/v1/webhook/composio"
MODULE = "app.api.v1.endpoints.webhook_composio"


# A real Composio auth config whose toolkit slug is GOOGLECALENDAR (oauth_config.py).
CALENDAR_AUTH_CONFIG_ID = "ac_exqcpnLvCzGJ"


def _expired_connection_event(
    toolkit: str = "NOTION",
    *,
    status: str = "EXPIRED",
    auth_config_id: str = "ac_test_config",
) -> dict:
    """A `composio.connected_account.expired` delivery, as the SDK's
    ``ConnectionExpiredEvent`` shapes it. It carries none of the trigger
    identifiers ``ComposioWebhookEvent`` requires — which is why the endpoint
    has to branch on the raw body before building that model."""
    return {
        "id": "msg_847cdfcd",
        "type": "composio.connected_account.expired",
        "timestamp": "2026-08-10T05:44:33Z",
        "metadata": {"project_id": "proj_x", "org_id": "org_x"},
        "data": {
            "id": "ca_xxxxxxxxxxxx",
            "user_id": "507f1f77bcf86cd799439011",
            "status": status,
            "status_reason": "refresh_token_revoked",
            "is_disabled": False,
            "toolkit": {"slug": toolkit},
            "auth_config": {
                "id": auth_config_id,
                "auth_scheme": "OAUTH2",
                "is_composio_managed": True,
                "is_disabled": False,
            },
            "state": {"authScheme": "OAUTH2", "val": {"status": status}},
            "data": {},
            "params": {},
            "created_at": "2026-05-02T09:12:44Z",
            "updated_at": "2026-08-10T05:44:33Z",
        },
    }


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

    async def test_the_drop_is_logged_with_the_type_that_arrived(
        self, unauthed_client: AsyncClient
    ) -> None:
        """Composio publishes no schema for this, so the logged type is the only
        evidence of what it actually sent."""
        with patch(f"{MODULE}.log") as mock_log:
            await unauthed_client.post(
                ENDPOINT,
                content=b"[]",
                headers={"content-type": "application/json", "webhook-id": "conn-nonobject-log"},
            )

        mock_log.error.assert_called_once()
        assert "not a JSON object" in mock_log.error.call_args.args[0]
        assert mock_log.error.call_args.kwargs == {"body_type": "list"}


@pytest.mark.usefixtures("_accepted_delivery")
class TestConnectionEventRouting:
    """A connection-lifecycle event carries none of the trigger identifiers the
    trigger model requires, so routing it on the RAW body — before any model is
    built — is what keeps it from raising instead of being handled."""

    async def test_an_expired_connection_event_is_routed_to_the_connection_handler(
        self, unauthed_client: AsyncClient
    ) -> None:
        body = _expired_connection_event()

        with patch(f"{MODULE}.spawn_logged_task") as spawn:
            response = await unauthed_client.post(
                ENDPOINT,
                content=json.dumps(body).encode(),
                headers={"content-type": "application/json", "webhook-id": "conn-expired-1"},
            )

        assert response.status_code == 200
        assert response.json()["message"] == "Connection event accepted"
        spawn.assert_called_once()

    async def test_the_handler_receives_the_delivered_body_not_a_placeholder(
        self, unauthed_client: AsyncClient
    ) -> None:
        """The toolkit in THIS delivery is what decides which integration expires."""
        body = _expired_connection_event(toolkit="NOT_A_REAL_TOOLKIT")

        response = await unauthed_client.post(
            ENDPOINT,
            content=json.dumps(body).encode(),
            headers={"content-type": "application/json", "webhook-id": "conn-expired-2"},
        )

        assert response.status_code == 200
        assert response.json()["message"] == "Unknown integration ignored"


async def _post_event(client: AsyncClient, body: dict, webhook_id: str):
    return await client.post(
        ENDPOINT,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json", "webhook-id": webhook_id},
    )


def _ns_fields(log_mock) -> dict:
    """Every field folded onto the ``composio_connection`` wide-event namespace."""
    fields: dict = {}
    for c in log_mock.set_ns.call_args_list:
        assert c.args[0] == "composio_connection", f"wrong namespace: {c.args[0]}"
        fields.update(c.kwargs)
    return fields


def _set_fields(log_mock) -> dict:
    fields: dict = {}
    for c in log_mock.set.call_args_list:
        fields.update(c.kwargs)
    return fields


@pytest.mark.usefixtures("_accepted_delivery")
class TestConnectionEventOutcomes:
    """Every branch acknowledges — a non-2xx makes Composio redeliver an event it
    can never send differently — so the ack MESSAGE is the only thing that says
    which branch ran, both to a reader and to this suite."""

    async def test_a_status_that_is_not_terminal_is_acked_without_expiring(
        self, unauthed_client: AsyncClient
    ) -> None:
        """INITIALIZING/ACTIVE arrive on the same event; expiring on them would
        kill a connection that is merely mid-handshake."""
        body = _expired_connection_event(status="INITIALIZING")

        with patch(f"{MODULE}.spawn_logged_task") as spawn:
            response = await _post_event(unauthed_client, body, "conn-live-status")

        assert response.json()["message"] == "Connection status not terminal"
        spawn.assert_not_called()

    async def test_an_envelope_that_does_not_parse_is_acked_and_logged(
        self, unauthed_client: AsyncClient
    ) -> None:
        body = _expired_connection_event()
        del body["data"]["toolkit"]

        with patch(f"{MODULE}.log") as mock_log:
            response = await _post_event(unauthed_client, body, "conn-unparseable")

        assert response.json()["message"] == "Connection event not understood"
        mock_log.error.assert_called_once()
        assert "Unparseable connection event" in mock_log.error.call_args.args[0]
        kwargs = mock_log.error.call_args.kwargs
        assert kwargs["event_type"] == "composio.connected_account.expired"
        assert kwargs["error_type"] == "ValidationError"
        # The text, not just its presence: this string is the only thing that says
        # WHICH field Composio omitted, and it is what a reader debugs from.
        assert "toolkit" in kwargs["error"]

    async def test_an_unrecognised_toolkit_is_logged_with_what_arrived(
        self, unauthed_client: AsyncClient
    ) -> None:
        """Composio can add a toolkit before GAIA maps it — the warning is the
        only signal that a real user's connection died unhandled."""
        body = _expired_connection_event(toolkit="NOT_A_REAL_TOOLKIT")

        with patch(f"{MODULE}.log") as mock_log:
            response = await _post_event(unauthed_client, body, "conn-unknown-toolkit")

        assert response.json()["message"] == "Unknown integration ignored"
        mock_log.warning.assert_called_once()
        assert "unrecognised integration" in mock_log.warning.call_args.args[0]
        assert mock_log.warning.call_args.kwargs == {
            "toolkit": "NOT_A_REAL_TOOLKIT",
            "auth_config_id": "ac_test_config",
        }

    async def test_the_auth_config_identifies_the_integration_when_the_toolkit_does_not(
        self, unauthed_client: AsyncClient
    ) -> None:
        """Composio identifies the connection by auth config; the toolkit slug is a
        fallback. Dropping the auth-config lookup strands every event whose slug
        GAIA does not map."""
        body = _expired_connection_event(
            toolkit="NOT_A_REAL_TOOLKIT", auth_config_id=CALENDAR_AUTH_CONFIG_ID
        )

        with patch(f"{MODULE}.spawn_logged_task") as spawn:
            response = await _post_event(unauthed_client, body, "conn-by-auth-config")

        assert response.json()["message"] == "Connection event accepted"
        spawn.assert_called_once()


@pytest.mark.usefixtures("_accepted_delivery")
class TestTheExpiryIsHandedOffCorrectly:
    async def test_the_background_task_carries_this_account_user_and_reason(
        self, unauthed_client: AsyncClient
    ) -> None:
        """These four values are what the expiry transition acts on: the wrong user
        expires a stranger's integration, the wrong account id fails to invalidate
        the dead one."""
        body = _expired_connection_event()

        # A plain MagicMock, not the auto-specced AsyncMock: the handler passes the
        # coroutine along without awaiting it, so a real one would only leak.
        expire = MagicMock(return_value="the-coroutine")
        with (
            patch(f"{MODULE}.spawn_logged_task") as spawn,
            patch(f"{MODULE}._expire_connection", expire),
        ):
            response = await _post_event(unauthed_client, body, "conn-handoff")

        assert response.json()["message"] == "Connection event accepted"
        expire.assert_called_once_with(
            "507f1f77bcf86cd799439011", "notion", "refresh_token_revoked", "ca_xxxxxxxxxxxx"
        )
        assert spawn.call_args.args == ("composio_connection_expiry", "the-coroutine")
        assert spawn.call_args.kwargs == {
            "user": {"id": "507f1f77bcf86cd799439011"},
            "webhook": {
                "event_type": "composio.connected_account.expired",
                "integration_id": "notion",
            },
        }

    async def test_the_wide_event_records_the_connection_it_acted_on(
        self, unauthed_client: AsyncClient
    ) -> None:
        """The webhook runs with no user watching, so this event is the only record
        — and it must never carry `state`, which holds the account's tokens."""
        body = _expired_connection_event()

        with patch(f"{MODULE}.spawn_logged_task"), patch(f"{MODULE}.log") as mock_log:
            await _post_event(unauthed_client, body, "conn-wide-event")

        assert _ns_fields(mock_log) == {
            "envelope_keys": ["data", "id", "metadata", "timestamp", "type"],
            "data_keys": sorted(body["data"]),
            "connected_account_id": "ca_xxxxxxxxxxxx",
            "status": "EXPIRED",
            "status_reason": "refresh_token_revoked",
            "toolkit": "NOTION",
            "auth_config_id": "ac_test_config",
            "integration_id": "notion",
        }
        assert _set_fields(mock_log) == {
            "user": {"id": "507f1f77bcf86cd799439011"},
            "operation": "webhook_accepted",
            "outcome": "success",
        }
