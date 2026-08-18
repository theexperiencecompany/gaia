"""The Composio SDK call `connect_account` actually makes.

Every other test of this path mocks `self.composio`, so they pass whatever the
SDK's real signature is — including after it changes under us. These bind GAIA's
call against the installed SDK instead, which is the only thing here that fails
when Composio moves the contract.

`link()` replaced `initiate()`: the legacy `POST /api/v3/connected_accounts`
behind initiate() is retired for Composio-managed OAuth (cutover 2026-07-03),
after which the SDK raises ComposioLegacyConnectedAccountsEndpointRetiredError.
"""

import inspect

from composio.core.models.connected_accounts import ConnectedAccounts, ConnectionRequest


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
