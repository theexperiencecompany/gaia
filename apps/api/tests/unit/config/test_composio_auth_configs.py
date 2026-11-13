"""Refusing Composio auth config ids that could never connect."""

import pytest

from app.config.composio_auth_configs import check_auth_config_ids
from app.config.oauth_config import OAUTH_INTEGRATIONS

ORIGIN = "COMPOSIO_AUTH_CONFIG_OVERRIDES"


def test_ids_for_composio_integrations_pass() -> None:
    check_auth_config_ids(OAUTH_INTEGRATIONS, {"gmail": "ac_g", "slack": "ac_s"}, origin=ORIGIN)
    check_auth_config_ids(OAUTH_INTEGRATIONS, {}, origin=ORIGIN)


@pytest.mark.parametrize("integration_id", ["gmial", "deepwiki"], ids=["typo", "not_composio"])
def test_an_id_for_no_composio_integration_is_refused(integration_id: str) -> None:
    with pytest.raises(ValueError) as exc:
        check_auth_config_ids(
            OAUTH_INTEGRATIONS, {integration_id: "ac_x", "gmail": "ac_y"}, origin=ORIGIN
        )

    assert str(exc.value) == f"{ORIGIN} names no Composio integration: ['{integration_id}']"


def test_an_empty_auth_config_id_is_refused() -> None:
    with pytest.raises(ValueError) as exc:
        check_auth_config_ids(OAUTH_INTEGRATIONS, {"gmail": "  ", "slack": "ac_s"}, origin=ORIGIN)

    assert str(exc.value) == f"{ORIGIN} has an empty auth config id: ['gmail']"
