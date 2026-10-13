"""The deployment profile: one capability set per ENV/AUTH_MODE pair."""

import pytest

from app.config.deployment import (
    DeploymentKind,
    InvalidDeploymentError,
    deployment_profile,
)


def test_production_bills_enforces_and_reads_env_only() -> None:
    profile = deployment_profile(
        DeploymentKind.PRODUCTION, "workos", unlimited_usage=False, local_code_sandbox=False
    )

    assert profile.bills is True
    assert profile.enforces_plans is True
    assert profile.enforces_usage_limits is True
    assert profile.runtime_credentials is False
    assert profile.local_auth is False
    assert profile.hosted_models is True
    assert profile.catalog_composio_auth_configs is True


def test_production_with_local_auth_is_refused() -> None:
    with pytest.raises(InvalidDeploymentError, match=r"AUTH_MODE=local.*ENV=production"):
        deployment_profile(
            DeploymentKind.PRODUCTION, "local", unlimited_usage=False, local_code_sandbox=False
        )


def test_selfhost_has_no_plans_no_limits_and_a_credential_store() -> None:
    profile = deployment_profile(
        DeploymentKind.SELFHOST, "local", unlimited_usage=False, local_code_sandbox=False
    )

    assert profile.bills is False
    assert profile.enforces_plans is False
    assert profile.enforces_usage_limits is False
    assert profile.runtime_credentials is True
    assert profile.local_auth is True
    assert profile.hosted_models is False
    assert profile.catalog_composio_auth_configs is False
    assert profile.local_code_sandbox is False


def test_selfhost_runs_the_local_code_sandbox_only_when_opted_in() -> None:
    profile = deployment_profile(
        DeploymentKind.SELFHOST, "local", unlimited_usage=False, local_code_sandbox=True
    )

    assert profile.local_code_sandbox is True


@pytest.mark.parametrize("kind", [DeploymentKind.PRODUCTION, DeploymentKind.DEVELOPMENT])
def test_the_local_code_sandbox_opt_in_is_ignored_outside_selfhost(kind: DeploymentKind) -> None:
    profile = deployment_profile(kind, "workos", unlimited_usage=False, local_code_sandbox=True)

    assert profile.local_code_sandbox is False


def test_selfhost_with_workos_still_stores_credentials() -> None:
    profile = deployment_profile(
        DeploymentKind.SELFHOST, "workos", unlimited_usage=False, local_code_sandbox=False
    )

    assert profile.runtime_credentials is True
    assert profile.local_auth is False


def test_development_mirrors_production_enforcement_without_billing() -> None:
    profile = deployment_profile(
        DeploymentKind.DEVELOPMENT, "workos", unlimited_usage=False, local_code_sandbox=False
    )

    assert profile.bills is False
    assert profile.enforces_plans is True
    assert profile.enforces_usage_limits is True
    assert profile.runtime_credentials is False
    assert profile.hosted_models is False
    assert profile.catalog_composio_auth_configs is True


def test_development_with_local_auth_gets_the_setup_surface() -> None:
    profile = deployment_profile(
        DeploymentKind.DEVELOPMENT, "local", unlimited_usage=False, local_code_sandbox=False
    )

    assert profile.local_auth is True
    assert profile.runtime_credentials is True
    assert profile.enforces_plans is True


def test_unlimited_usage_lifts_limits_but_keeps_plans() -> None:
    profile = deployment_profile(
        DeploymentKind.DEVELOPMENT, "workos", unlimited_usage=True, local_code_sandbox=False
    )

    assert profile.enforces_usage_limits is False
    assert profile.enforces_plans is True
