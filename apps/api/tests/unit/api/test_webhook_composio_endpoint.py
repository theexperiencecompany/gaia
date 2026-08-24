"""Tests for app/api/v1/endpoints/webhook_composio.py

The endpoint module is resolved at test time, never imported at module scope: on
the base revision, importing it standalone trips a circular import
(triggers -> workflow -> trigger_service -> triggers) that this branch removes by
emptying the dead `app/services/workflow/__init__.py` barrel. The regression lane
replays the marked test below against that revision, where a module-scope import
would fail at collection and prove nothing.
"""

import asyncio
import importlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

from app.models.webhook_models import ComposioWebhookEvent

ENDPOINT = "/api/v1/webhook/composio"
MODULE = "app.api.v1.endpoints.webhook_composio"


def _endpoint():
    """The endpoint module, resolved on use — see the module docstring."""
    return importlib.import_module(MODULE)


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


class TestTheBackgroundExpiry:
    """Runs detached from the request, so nothing is watching it: a stall that
    logged nothing would leave a user's integration reading as connected forever
    with no trace of why."""

    async def test_it_pauses_the_dependent_workflows_before_expiring_them(self) -> None:
        """The paused titles become the notification copy ("2 workflows are
        paused"), so the pause has to complete first and hand them over."""
        with (
            patch(
                f"{MODULE}.pause_workflows_for_expired_integration",
                AsyncMock(return_value=["Morning digest"]),
            ) as pause,
            patch(f"{MODULE}.expire_user_integration", AsyncMock()) as expire,
        ):
            await _endpoint()._expire_connection("user-1", "gmail", "refresh_token_revoked", "ca_1")

        pause.assert_awaited_once_with("user-1", "gmail")
        expire.assert_awaited_once_with(
            "user-1",
            "gmail",
            reason="refresh_token_revoked",
            trigger="webhook",
            notify=True,
            connected_account_id="ca_1",
            paused_workflows=["Morning digest"],
        )

    async def test_a_stall_is_logged_rather_than_disappearing_with_the_task(self) -> None:
        async def _never_finishes(*_a: object, **_k: object) -> list[str]:
            await asyncio.sleep(10)
            return []

        with (
            patch(f"{MODULE}.WEBHOOK_TASK_TIMEOUT", 0.01),
            patch(f"{MODULE}.pause_workflows_for_expired_integration", _never_finishes),
            patch(f"{MODULE}.expire_user_integration", AsyncMock()) as expire,
            patch(f"{MODULE}.log") as mock_log,
        ):
            await _endpoint()._expire_connection("user-1", "gmail", "revoked", "ca_1")

        expire.assert_not_awaited()
        mock_log.error.assert_called_once()
        assert "timed out" in mock_log.error.call_args.args[0].lower()
        assert mock_log.error.call_args.kwargs == {
            "timeout_s": 0.01,
            "user_id": "user-1",
            "integration_id": "gmail",
        }


def _trigger_event(event_type: str = "gmail_new_gmail_message") -> dict:
    """A Composio *trigger* delivery — the other branch of this endpoint."""
    return {
        "type": event_type,
        "timestamp": "2026-08-10T05:44:33Z",
        "data": {
            "connection_id": "conn-1",
            "connection_nano_id": "nano-1",
            "trigger_nano_id": "trig-nano-1",
            "trigger_id": "trig-1",
            "user_id": "507f1f77bcf86cd799439011",
            "payload": {"subject": "hi"},
        },
    }


class TestDeliveryGuards:
    """Signature and replay run before anything reads the body — Composio retries
    aggressively, so a delivery processed twice is a workflow fired twice."""

    async def test_every_delivery_is_signature_checked_against_its_own_request(
        self, unauthed_client: AsyncClient
    ) -> None:
        redis = MagicMock()
        redis.client.set = AsyncMock(return_value=True)
        with (
            patch(f"{MODULE}.verify_composio_webhook_signature", AsyncMock()) as verify,
            patch(f"{MODULE}.redis_cache", redis),
        ):
            await _post_event(unauthed_client, _trigger_event(), "sig-check-1")

        verify.assert_awaited_once()
        # The real request, not a placeholder: the signature is computed over this
        # delivery's headers and body.
        assert verify.await_args.args[0].url.path == ENDPOINT

    async def test_the_delivery_id_claims_a_dedupe_key_that_expires(
        self, unauthed_client: AsyncClient
    ) -> None:
        redis = MagicMock()
        redis.client.set = AsyncMock(return_value=True)
        with (
            patch(f"{MODULE}.verify_composio_webhook_signature", AsyncMock()),
            patch(f"{MODULE}.redis_cache", redis),
        ):
            await _post_event(unauthed_client, _trigger_event(), "dedupe-key-1")

        redis.client.set.assert_awaited_once_with(
            "webhook:composio:dedupe-key-1", "1", nx=True, ex=3600
        )

    async def test_a_delivery_whose_key_is_already_claimed_does_no_work(
        self, unauthed_client: AsyncClient
    ) -> None:
        redis = MagicMock()
        # `nx` set returns falsy when the key already exists.
        redis.client.set = AsyncMock(return_value=None)
        with (
            patch(f"{MODULE}.verify_composio_webhook_signature", AsyncMock()),
            patch(f"{MODULE}.redis_cache", redis),
            patch(f"{MODULE}.get_handler_by_event") as handler,
        ):
            response = await _post_event(unauthed_client, _trigger_event(), "dupe-1")

        assert response.json()["message"] == "Duplicate webhook ignored"
        handler.assert_not_called()


@pytest.mark.usefixtures("_accepted_delivery")
class TestTriggerEventRouting:
    async def test_the_event_is_built_from_this_delivery_and_routed_by_its_type(
        self, unauthed_client: AsyncClient
    ) -> None:
        """Every identifier the handler acts on comes off this body — a dropped
        trigger_id or user_id routes someone else's automation."""
        with patch(f"{MODULE}.get_handler_by_event") as get_handler:
            get_handler.return_value = None  # unhandled: stops before dispatch
            response = await _post_event(unauthed_client, _trigger_event(), "trigger-1")

        assert response.json()["message"] == "Webhook received"
        get_handler.assert_called_once_with("GMAIL_NEW_GMAIL_MESSAGE")

    async def test_the_wide_event_identifies_the_user_and_trigger(
        self, unauthed_client: AsyncClient
    ) -> None:
        with (
            patch(f"{MODULE}.get_handler_by_event", return_value=None),
            patch(f"{MODULE}.log") as mock_log,
        ):
            await _post_event(unauthed_client, _trigger_event(), "trigger-2")

        fields = _set_fields(mock_log)
        assert fields["user"] == {"id": "507f1f77bcf86cd799439011"}
        assert fields["webhook"] == {
            "event_type": "GMAIL_NEW_GMAIL_MESSAGE",
            "trigger_id": "trig-1",
        }

    async def test_a_recognised_trigger_is_dispatched_with_the_parsed_event(
        self, unauthed_client: AsyncClient
    ) -> None:
        handler = MagicMock()
        with (
            patch(f"{MODULE}.get_handler_by_event", return_value=handler),
            patch(f"{MODULE}.spawn_logged_task") as spawn,
            patch(f"{MODULE}._process_webhook_event") as process,
        ):
            process.return_value = "the-coroutine"
            response = await _post_event(unauthed_client, _trigger_event(), "trigger-3")

        assert response.json()["message"] == "Webhook accepted"
        event = process.call_args.args[1]
        assert event.trigger_id == "trig-1"
        assert event.connection_id == "conn-1"
        assert event.connection_nano_id == "nano-1"
        assert event.trigger_nano_id == "trig-nano-1"
        assert event.user_id == "507f1f77bcf86cd799439011"
        assert event.timestamp == "2026-08-10T05:44:33Z"
        assert event.data["payload"] == {"subject": "hi"}
        spawn.assert_called_once()


@pytest.mark.usefixtures("_accepted_delivery")
class TestDeliveryWithoutAnId:
    async def test_a_delivery_with_no_id_header_is_processed_without_claiming_a_key(
        self, unauthed_client: AsyncClient
    ) -> None:
        """Composio always sends `webhook-id`, but a missing one must not invent a
        dedupe key — one bogus key would swallow every later delivery that reused
        it as a duplicate."""
        redis = MagicMock()
        redis.client.set = AsyncMock(return_value=True)
        with (
            patch(f"{MODULE}.verify_composio_webhook_signature", AsyncMock()),
            patch(f"{MODULE}.redis_cache", redis),
            patch(f"{MODULE}.get_handler_by_event", return_value=None) as get_handler,
        ):
            response = await unauthed_client.post(
                ENDPOINT,
                content=json.dumps(_trigger_event()).encode(),
                headers={"content-type": "application/json"},
            )

        assert response.json()["message"] == "Webhook received"
        redis.client.set.assert_not_awaited()
        get_handler.assert_called_once()


class TestBackgroundTriggerProcessing:
    async def test_the_handler_gets_the_nano_id_it_actually_matches_on(self) -> None:
        """Handlers match `trigger_config.composio_trigger_ids`, which stores the
        NANO id from triggers.create(). Forwarding the internal UUID instead never
        matches, so the workflow silently never fires."""
        handler = MagicMock()
        handler.process_event = AsyncMock()
        event = ComposioWebhookEvent(
            connection_id="conn-1",
            connection_nano_id="nano-1",
            trigger_nano_id="ti_nano",
            trigger_id="uuid-1",
            user_id="user-1",
            data={"payload": 1},
            timestamp="2026-08-10T05:44:33Z",
            type="gmail_new_gmail_message",
        )

        await _endpoint()._process_webhook_event(handler, event)

        handler.process_event.assert_awaited_once_with(
            event_type="GMAIL_NEW_GMAIL_MESSAGE",
            trigger_id="ti_nano",
            user_id="user-1",
            data={"payload": 1},
        )

    async def test_it_falls_back_to_the_uuid_when_no_nano_id_arrived(self) -> None:
        handler = MagicMock()
        handler.process_event = AsyncMock()
        event = ComposioWebhookEvent(
            connection_id="conn-1",
            connection_nano_id="nano-1",
            trigger_nano_id="",
            trigger_id="uuid-1",
            user_id="user-1",
            data={},
            timestamp="2026-08-10T05:44:33Z",
            type="gmail_new_gmail_message",
        )

        await _endpoint()._process_webhook_event(handler, event)

        assert handler.process_event.await_args.kwargs["trigger_id"] == "uuid-1"
