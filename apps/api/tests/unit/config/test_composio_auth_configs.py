"""Overriding the catalog's Composio auth config ids for a non-production project."""

import pytest

from app.config.composio_auth_configs import with_auth_config_overrides
from app.config.oauth_config import OAUTH_INTEGRATIONS, get_integration_by_id
from app.models.oauth_models import OAuthIntegration

GMAIL = get_integration_by_id("gmail")


def _auth_config_ids(integrations: list[OAuthIntegration]) -> dict[str, str]:
    return {i.id: i.composio_config.auth_config_id for i in integrations if i.composio_config}


def test_an_override_moves_only_that_integration_to_the_new_auth_config() -> None:
    assert GMAIL is not None and GMAIL.composio_config is not None
    production_ids = _auth_config_ids(OAUTH_INTEGRATIONS)

    result = with_auth_config_overrides(OAUTH_INTEGRATIONS, {"gmail": " ac_dev_gmail "})

    assert _auth_config_ids(result) == {**production_ids, "gmail": "ac_dev_gmail"}
    gmail = next(i for i in result if i.id == "gmail")
    assert gmail.composio_config is not None
    assert gmail.composio_config.toolkit == GMAIL.composio_config.toolkit
    assert gmail.composio_config.toolkit_version == GMAIL.composio_config.toolkit_version
    assert GMAIL.composio_config.auth_config_id == production_ids["gmail"]
    assert [i.id for i in result] == [i.id for i in OAUTH_INTEGRATIONS]


def test_no_overrides_leaves_the_catalog_as_declared() -> None:
    assert with_auth_config_overrides(OAUTH_INTEGRATIONS, {}) == OAUTH_INTEGRATIONS


@pytest.mark.parametrize("integration_id", ["gmial", "deepwiki"], ids=["typo", "not_composio"])
def test_an_override_for_no_composio_integration_refuses_to_load(integration_id: str) -> None:
    with pytest.raises(ValueError) as exc:
        with_auth_config_overrides(OAUTH_INTEGRATIONS, {integration_id: "ac_x", "gmail": "ac_y"})

    assert str(exc.value) == (
        f"COMPOSIO_AUTH_CONFIG_OVERRIDES names no Composio integration: ['{integration_id}']"
    )


def test_an_empty_auth_config_id_refuses_to_load() -> None:
    with pytest.raises(ValueError) as exc:
        with_auth_config_overrides(OAUTH_INTEGRATIONS, {"gmail": "  ", "slack": "ac_s"})

    assert str(exc.value) == (
        "COMPOSIO_AUTH_CONFIG_OVERRIDES has an empty auth config id: ['gmail']"
    )
