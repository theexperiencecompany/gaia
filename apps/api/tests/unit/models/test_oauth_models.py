"""Unit tests for the platform catalog entry's transport invariants.

``OAuthIntegration`` is the shape of every row in ``oauth_config``. The connect
dispatch and the subagent tool factory both branch on ``managed_by`` and then
reach straight for the matching config block, so a row where the two disagree
does not fail at import — it fails much later as an integration that resolves
to nothing. The validator exists to turn that into a config error the moment
the catalog is loaded, and these tests pin both directions of it.
"""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from app.models.cli_config import CliAuthSpec, CliConfig
from app.models.mcp_config import ComposioConfig
from app.models.oauth_models import OAuthIntegration

CLI_CONFIG = CliConfig(
    command="link-cli",
    install_command="npm install @stripe/link-cli",
    auth=CliAuthSpec(kind="none", verify_command="link-cli auth status"),
)


def _integration(**overrides: object) -> OAuthIntegration:
    base: dict[str, object] = {
        "id": "stripe_link",
        "name": "Stripe Link",
        "description": "Pay for things",
        "category": "business",
        "provider": "stripe_link",
        "scopes": [],
    }
    base.update(overrides)
    return OAuthIntegration(**base)  # type: ignore[arg-type]  # kwargs dict widens to object; the model validates the real types


class TestCliTransportInvariant:
    def test_a_cli_row_without_a_cli_config_is_rejected_by_name(self):
        # The tool factory reads cli_config immediately after selecting on
        # managed_by; without one the integration would offer a Connect button
        # that resolves to nothing. The message names the row so the catalog
        # entry can be found.
        with pytest.raises(ValidationError) as exc_info:
            _integration(managed_by="cli")

        assert "Integration 'stripe_link' has managed_by='cli' but no cli_config." in str(
            exc_info.value
        )

    def test_a_cli_config_on_a_non_cli_row_is_rejected_and_names_the_transport(self):
        # The other direction: a config block nothing will ever read. The
        # message has to say which transport the row actually claims, because
        # that is the half that is wrong.
        with pytest.raises(ValidationError) as exc_info:
            _integration(
                managed_by="composio",
                composio_config=ComposioConfig(auth_config_id="ac_1", toolkit="stripe"),
                cli_config=CLI_CONFIG,
            )

        assert (
            "Integration 'stripe_link' sets cli_config but managed_by='composio'; expected 'cli'."
            in str(exc_info.value)
        )

    def test_a_coherent_cli_row_is_accepted(self):
        integration = _integration(managed_by="cli", cli_config=CLI_CONFIG)

        assert integration.managed_by == "cli"
        assert integration.cli_config is CLI_CONFIG

    @pytest.mark.parametrize("managed_by", ["self", "mcp", "internal"])
    def test_the_other_transports_need_no_cli_config(self, managed_by: str):
        # Only the exact string "cli" selects the CLI branch; a validator that
        # matched more loosely would demand a cli_config from every OAuth row
        # in the catalog and break startup.
        integration = _integration(managed_by=managed_by)

        assert integration.cli_config is None


class TestComposioTransportInvariant:
    def test_a_composio_row_without_a_composio_config_is_rejected(self):
        with pytest.raises(ValidationError, match="no composio_config"):
            _integration(managed_by="composio")

    def test_a_composio_config_on_a_non_composio_row_is_rejected(self):
        with pytest.raises(ValidationError, match="expected 'composio'"):
            _integration(
                managed_by="mcp",
                composio_config=ComposioConfig(auth_config_id="ac_1", toolkit="stripe"),
            )
