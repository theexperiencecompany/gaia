"""The Composio SDK call `connect_account` actually makes.

Every other test of this path mocks `self.composio`, so they pass whatever the
SDK's real signature is — including after it changes under us. These bind GAIA's
call against the installed SDK instead, which is the only thing here that fails
when Composio moves the contract.

`link()` replaced `initiate()`: the legacy `POST /api/v3/connected_accounts`
behind initiate() is retired for Composio-managed OAuth (cutover 2026-07-03),
after which the SDK raises ComposioLegacyConnectedAccountsEndpointRetiredError.

The same reasoning covers the other half of the connection lifecycle: the status
values and the event name the expiry webhook gates on are Composio's vocabulary,
not ours, so they are pinned here against the installed SDK too.
"""

import inspect

from composio.core.models.connected_accounts import (
    _TERMINAL_CONNECTION_STATES,
    ConnectedAccounts,
    ConnectionRequest,
)
from composio.core.models.webhook_events import (
    ConnectionStatusEnum,
    WebhookEventType,
    is_connection_expired_event,
)


class TestConnectAccountSdkContract:
    def test_link_accepts_exactly_the_arguments_connect_account_passes(self) -> None:
        bound = inspect.signature(ConnectedAccounts.link).bind(
            None,  # self
            user_id="user-1",
            auth_config_id="ac_test",
            callback_url="https://gaia.test/callback",
            allow_multiple=True,
        )
        bound.apply_defaults()

        assert bound.arguments["user_id"] == "user-1"
        assert bound.arguments["auth_config_id"] == "ac_test"
        assert bound.arguments["callback_url"] == "https://gaia.test/callback"
        # allow_multiple=True is load-bearing: an EXPIRED account does not block a
        # reconnect (the SDK's guard filters statuses=["ACTIVE"]), but a live one
        # would raise ComposioMultipleConnectedAccountsError without this.
        assert bound.arguments["allow_multiple"] is True

    def test_the_connection_request_exposes_the_fields_connect_account_reads(self) -> None:
        request = ConnectionRequest(
            id="ca_test",
            status="INITIATED",
            redirect_url="https://connect.composio.dev/x",
            client=None,
        )

        # connect_account returns these two straight to the caller; `id` is also
        # what GAIA persists as `connected_account_id`.
        assert request.id == "ca_test"
        assert request.redirect_url == "https://connect.composio.dev/x"


class TestDeadConnectionStatusContract:
    """`constants.integrations.DEAD_CONNECTION_STATUSES` expires an integration on
    EXPIRED/REVOKED/FAILED. If Composio renames one of those, the webhook stops
    matching and silently never expires anything — the failure mode is silence,
    so only a binding against the real enum catches it."""

    def test_the_statuses_the_webhook_gates_on_still_exist(self) -> None:
        assert ConnectionStatusEnum.EXPIRED.value == "EXPIRED"
        assert ConnectionStatusEnum.REVOKED.value == "REVOKED"
        assert ConnectionStatusEnum.FAILED.value == "FAILED"

    def test_inactive_is_still_a_recoverable_state_and_not_terminal(self) -> None:
        # INACTIVE is excluded from the gate on purpose — it can recover to
        # ACTIVE, so expiring on it would nag a user whose account is fine.
        assert ConnectionStatusEnum.INACTIVE.value == "INACTIVE"
        assert ConnectionStatusEnum.INACTIVE.value not in _TERMINAL_CONNECTION_STATES

        # Our gate is a copy of the SDK's own notion of terminal; if Composio
        # adds or reclassifies one, that is a decision we have to make too.
        assert frozenset({"EXPIRED", "REVOKED", "FAILED"}) == _TERMINAL_CONNECTION_STATES


class TestConnectionExpiredEventContract:
    """The endpoint routes on `is_connection_expired_event(body)` before building
    any model, so a renamed event name would fall through to the trigger path
    instead of erroring."""

    def test_the_type_guard_accepts_the_expiry_delivery_and_rejects_a_trigger(self) -> None:
        expired = {
            "id": "msg_847cdfcd",
            "type": "composio.connected_account.expired",
            "timestamp": "2026-08-10T05:44:33Z",
            "data": {"id": "ca_x", "user_id": "u1", "status": "EXPIRED"},
        }
        trigger = {
            "id": "msg_deadbeef",
            "type": "composio.trigger.message",
            "timestamp": "2026-08-10T05:44:33Z",
            "data": {"trigger_nano_id": "ti_x", "user_id": "u1"},
        }

        assert is_connection_expired_event(expired) is True
        assert is_connection_expired_event(trigger) is False

    def test_the_event_name_literal_is_unchanged(self) -> None:
        assert WebhookEventType.CONNECTION_EXPIRED.value == "composio.connected_account.expired"
