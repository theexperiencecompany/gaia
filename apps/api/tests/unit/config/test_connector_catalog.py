"""The connector catalog's contract: every shipped spec can connect, verify read-only and name the account."""

import pytest

from app.config.connector_catalog import CONNECTOR_CATALOG
from app.config.oauth_config import OAUTH_INTEGRATIONS, get_integration_by_id
from app.models.connector_models import ConnectorKind, ConnectorSpec, CpuArch, PackageManager
from app.models.oauth_models import OAuthIntegration
from app.services.connectors.commands import plan_call

_IDS = [entry.id for entry in CONNECTOR_CATALOG]


def _entry(connector_id: str) -> OAuthIntegration:
    entry = get_integration_by_id(connector_id)
    assert entry is not None
    return entry


def _spec(connector_id: str) -> ConnectorSpec:
    spec = _entry(connector_id).connector_config
    assert spec is not None
    return spec


def test_catalog_ids_are_unique_across_every_platform_integration() -> None:
    ids = [integration.id for integration in OAUTH_INTEGRATIONS]

    assert len(ids) == len(set(ids))
    assert set(_IDS) <= set(ids)


@pytest.mark.parametrize("connector_id", _IDS)
def test_a_catalog_connector_is_a_bearer_platform_integration(connector_id: str) -> None:
    entry = _entry(connector_id)

    assert entry.managed_by == "connector"
    assert entry.auth_type == "bearer"
    assert entry.requires_auth
    assert entry.icon_url


@pytest.mark.parametrize("connector_id", _IDS)
def test_the_card_links_to_where_the_key_is_made(connector_id: str) -> None:
    assert _spec(connector_id).credential.token_url is not None


@pytest.mark.parametrize("connector_id", _IDS)
def test_the_verify_call_names_the_account(connector_id: str) -> None:
    identity = _spec(connector_id).verify.identity

    assert identity.json_path or identity.regex


@pytest.mark.parametrize("connector_id", _IDS)
def test_the_verify_and_help_calls_never_ask_for_approval(connector_id: str) -> None:
    spec = _spec(connector_id)
    if spec.kind is ConnectorKind.SDK:
        pytest.skip("an SDK script cannot be classified, so every SDK call asks")

    assert not plan_call(spec, spec.verify.args).is_write
    if spec.kind is ConnectorKind.CLI:
        assert not plan_call(spec, spec.usage.help_args).is_write


@pytest.mark.parametrize("connector_id", _IDS)
def test_every_binary_ships_for_both_cloud_and_arm_self_host(connector_id: str) -> None:
    spec = _spec(connector_id)
    binaries = [p for p in spec.install if p.manager is PackageManager.BINARY]
    if not binaries:
        pytest.skip("no binary package")

    by_name: dict[str, set[CpuArch | None]] = {}
    for package in binaries:
        by_name.setdefault(package.name, set()).add(package.arch)
    assert all(arches == {CpuArch.AMD64, CpuArch.ARM64} for arches in by_name.values())
