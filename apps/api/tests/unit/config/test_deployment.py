"""The deployment profile: one capability set per ENV/AUTH_MODE pair."""

import pytest

from app.config.deployment import (
    BlobStoreKind,
    DeploymentKind,
    InvalidDeploymentError,
    deployment_profile,
)


def test_production_bills_enforces_and_reads_env_only() -> None:
    profile = deployment_profile(
        DeploymentKind.PRODUCTION,
        "workos",
        unlimited_usage=False,
        local_code_sandbox=False,
        blob_store=None,
    )

    assert profile.bills is True
    assert profile.product_analytics is True
    assert profile.enforces_plans is True
    assert profile.enforces_usage_limits is True
    assert profile.runtime_credentials is False
    assert profile.local_auth is False
    assert profile.hosted_models is True
    assert profile.catalog_composio_auth_configs is True
    assert profile.local_workspace is False
    assert profile.blob_store is BlobStoreKind.CLOUDINARY
    assert profile.gaia_support is True


def test_production_with_local_auth_is_refused() -> None:
    with pytest.raises(InvalidDeploymentError, match=r"AUTH_MODE=local.*ENV=production"):
        deployment_profile(
            DeploymentKind.PRODUCTION,
            "local",
            unlimited_usage=False,
            local_code_sandbox=False,
            blob_store=None,
        )


def test_selfhost_has_no_plans_no_limits_and_a_credential_store() -> None:
    profile = deployment_profile(
        DeploymentKind.SELFHOST,
        "local",
        unlimited_usage=False,
        local_code_sandbox=False,
        blob_store=None,
    )

    assert profile.bills is False
    assert profile.product_analytics is False
    assert profile.enforces_plans is False
    assert profile.enforces_usage_limits is False
    assert profile.runtime_credentials is True
    assert profile.local_auth is True
    assert profile.hosted_models is False
    assert profile.catalog_composio_auth_configs is False
    assert profile.local_code_sandbox is False
    assert profile.local_workspace is True
    assert profile.blob_store is BlobStoreKind.LOCAL
    assert profile.gaia_support is False


def test_selfhost_runs_the_local_code_sandbox_only_when_opted_in() -> None:
    profile = deployment_profile(
        DeploymentKind.SELFHOST,
        "local",
        unlimited_usage=False,
        local_code_sandbox=True,
        blob_store=None,
    )

    assert profile.local_code_sandbox is True


@pytest.mark.parametrize("kind", [DeploymentKind.PRODUCTION, DeploymentKind.DEVELOPMENT])
def test_the_local_code_sandbox_opt_in_is_ignored_outside_selfhost(kind: DeploymentKind) -> None:
    profile = deployment_profile(
        kind, "workos", unlimited_usage=False, local_code_sandbox=True, blob_store=None
    )

    assert profile.local_code_sandbox is False


def test_selfhost_with_workos_still_stores_credentials() -> None:
    profile = deployment_profile(
        DeploymentKind.SELFHOST,
        "workos",
        unlimited_usage=False,
        local_code_sandbox=False,
        blob_store=None,
    )

    assert profile.runtime_credentials is True
    assert profile.local_auth is False


def test_development_mirrors_production_enforcement_without_billing() -> None:
    profile = deployment_profile(
        DeploymentKind.DEVELOPMENT,
        "workos",
        unlimited_usage=False,
        local_code_sandbox=False,
        blob_store=None,
    )

    assert profile.bills is False
    assert profile.product_analytics is False
    assert profile.enforces_plans is True
    assert profile.enforces_usage_limits is True
    assert profile.runtime_credentials is False
    assert profile.hosted_models is False
    assert profile.catalog_composio_auth_configs is True
    assert profile.local_workspace is False
    assert profile.blob_store is BlobStoreKind.CLOUDINARY


def test_development_with_local_auth_gets_the_setup_surface() -> None:
    profile = deployment_profile(
        DeploymentKind.DEVELOPMENT,
        "local",
        unlimited_usage=False,
        local_code_sandbox=False,
        blob_store=None,
    )

    assert profile.local_auth is True
    assert profile.runtime_credentials is True
    assert profile.enforces_plans is True


def test_unlimited_usage_lifts_limits_but_keeps_plans() -> None:
    profile = deployment_profile(
        DeploymentKind.DEVELOPMENT,
        "workos",
        unlimited_usage=True,
        local_code_sandbox=False,
        blob_store=None,
    )

    assert profile.enforces_usage_limits is False
    assert profile.enforces_plans is True


def test_production_refuses_a_local_blob_store() -> None:
    with pytest.raises(InvalidDeploymentError, match=r"BLOB_STORE=local.*ENV=production"):
        deployment_profile(
            DeploymentKind.PRODUCTION,
            "workos",
            unlimited_usage=False,
            local_code_sandbox=False,
            blob_store=BlobStoreKind.LOCAL,
        )


def test_selfhost_may_choose_cloudinary_and_keeps_its_local_workspace() -> None:
    profile = deployment_profile(
        DeploymentKind.SELFHOST,
        "local",
        unlimited_usage=False,
        local_code_sandbox=False,
        blob_store=BlobStoreKind.CLOUDINARY,
    )

    assert profile.blob_store is BlobStoreKind.CLOUDINARY
    assert profile.local_workspace is True


@pytest.mark.parametrize("kind", [DeploymentKind.PRODUCTION, DeploymentKind.SELFHOST])
def test_real_deployments_fail_fast(kind: DeploymentKind) -> None:
    profile = deployment_profile(
        kind, "workos", unlimited_usage=False, local_code_sandbox=False, blob_store=None
    )

    assert profile.fail_fast is True


@pytest.mark.parametrize(
    ("kind", "refuses"),
    [
        (DeploymentKind.SELFHOST, True),
        (DeploymentKind.PRODUCTION, False),
        (DeploymentKind.DEVELOPMENT, False),
    ],
)
def test_only_selfhost_refuses_to_boot_with_a_required_key_unset(
    kind: DeploymentKind, refuses: bool
) -> None:
    profile = deployment_profile(
        kind, "workos", unlimited_usage=False, local_code_sandbox=False, blob_store=None
    )

    assert profile.requires_complete_config is refuses


def test_development_tolerates_missing_configuration() -> None:
    profile = deployment_profile(
        DeploymentKind.DEVELOPMENT,
        "workos",
        unlimited_usage=False,
        local_code_sandbox=False,
        blob_store=None,
    )

    assert profile.fail_fast is False
