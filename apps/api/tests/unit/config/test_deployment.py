"""The deployment profile: one capability set per ENV/AUTH_MODE pair."""

from collections.abc import Iterator

import pytest

from app.config.deployment import (
    AuthMode,
    BlobStoreKind,
    DeploymentKind,
    InvalidDeploymentError,
    OriginPolicy,
    baseline_profile,
    deployment_profile,
)


@pytest.fixture(autouse=True)
def _fresh_profiles() -> Iterator[None]:
    """Compute every profile in the test, not read one memoised by app import."""
    deployment_profile.cache_clear()
    yield
    deployment_profile.cache_clear()


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
    assert profile.instance_toolkits is False
    assert profile.private_network_endpoints is False
    assert profile.local_workspace is False
    assert profile.blob_store is BlobStoreKind.CLOUDINARY
    assert profile.gaia_support is True
    assert profile.hosted_bots is True


def test_production_with_local_auth_is_refused() -> None:
    with pytest.raises(
        InvalidDeploymentError,
        match=(
            r"^AUTH_MODE=local is set but ENV=production — local username/password "
            r"auth is a self-host feature and must never run against production\. "
            r"Use ENV=selfhost for local auth\.$"
        ),
    ):
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
    assert profile.instance_toolkits is True
    assert profile.private_network_endpoints is True
    assert profile.local_code_sandbox is False
    assert profile.local_workspace is True
    assert profile.blob_store is BlobStoreKind.LOCAL
    assert profile.gaia_support is False
    assert profile.hosted_bots is False


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
    assert profile.instance_toolkits is False
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
    assert profile.instance_toolkits is True
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
    with pytest.raises(
        InvalidDeploymentError,
        match=(
            r"^BLOB_STORE=local is set but ENV=production — hosted files are served "
            r"from Cloudinary and must never land on a container's local disk\.$"
        ),
    ):
        deployment_profile(
            DeploymentKind.PRODUCTION,
            "workos",
            unlimited_usage=False,
            local_code_sandbox=False,
            blob_store=BlobStoreKind.LOCAL,
        )


@pytest.mark.regression
def test_a_blob_store_named_by_its_string_value_gets_the_enum_member() -> None:
    """Regression: the cache keys "cloudinary" and BlobStoreKind.CLOUDINARY as one, so a str poisoned it."""
    args = {"unlimited_usage": False, "local_code_sandbox": False}
    by_value = deployment_profile(
        DeploymentKind.SELFHOST,
        "local",
        **args,
        blob_store="cloudinary",  # type: ignore[arg-type]  # why: an assigned setting skips pydantic validation
    )
    by_member = deployment_profile(
        DeploymentKind.SELFHOST, "local", **args, blob_store=BlobStoreKind.CLOUDINARY
    )

    assert by_value.blob_store is BlobStoreKind.CLOUDINARY
    assert by_member.blob_store is BlobStoreKind.CLOUDINARY


@pytest.mark.regression
def test_production_refuses_a_local_blob_store_named_by_its_string_value() -> None:
    with pytest.raises(InvalidDeploymentError, match=r"^BLOB_STORE=local is set"):
        deployment_profile(
            DeploymentKind.PRODUCTION,
            "workos",
            unlimited_usage=False,
            local_code_sandbox=False,
            blob_store="local",  # type: ignore[arg-type]  # why: an assigned setting skips pydantic validation
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


def test_selfhost_may_choose_the_local_blob_store_explicitly() -> None:
    profile = deployment_profile(
        DeploymentKind.SELFHOST,
        "local",
        unlimited_usage=False,
        local_code_sandbox=False,
        blob_store=BlobStoreKind.LOCAL,
    )

    assert profile.blob_store is BlobStoreKind.LOCAL


@pytest.mark.parametrize(
    ("kind", "origins", "public_readiness", "https_only", "private_endpoints", "dev_tools"),
    [
        (DeploymentKind.PRODUCTION, OriginPolicy.GAIA_CLOUD, False, True, False, False),
        (DeploymentKind.DEVELOPMENT, OriginPolicy.LOCAL_DEVELOPMENT, True, False, True, True),
        (DeploymentKind.SELFHOST, OriginPolicy.INSTANCE, True, False, True, False),
    ],
)
def test_each_kind_exposes_its_own_network_surface(
    kind: DeploymentKind,
    origins: OriginPolicy,
    public_readiness: bool,
    https_only: bool,
    private_endpoints: bool,
    dev_tools: bool,
) -> None:
    profile = deployment_profile(
        kind, "workos", unlimited_usage=False, local_code_sandbox=False, blob_store=None
    )

    assert profile.kind is kind
    assert profile.trusted_origins is origins
    assert profile.public_readiness is public_readiness
    assert profile.https_only is https_only
    assert profile.private_network_endpoints is private_endpoints
    assert profile.dev_tools is dev_tools


@pytest.mark.parametrize(
    ("kind", "searxng_first", "hosted_only_features"),
    [
        (DeploymentKind.PRODUCTION, False, True),
        (DeploymentKind.DEVELOPMENT, False, True),
        (DeploymentKind.SELFHOST, True, False),
    ],
)
def test_selfhost_prefers_searxng_and_runs_no_browser_or_voice(
    kind: DeploymentKind, searxng_first: bool, hosted_only_features: bool
) -> None:
    profile = deployment_profile(
        kind, "workos", unlimited_usage=False, local_code_sandbox=False, blob_store=None
    )

    assert profile.searxng_before_duckduckgo is searxng_first
    assert profile.browser_automation is hosted_only_features
    assert profile.voice is hosted_only_features


@pytest.mark.parametrize(
    ("kind", "auth_mode"),
    [
        (DeploymentKind.PRODUCTION, "workos"),
        (DeploymentKind.DEVELOPMENT, "workos"),
        (DeploymentKind.SELFHOST, "local"),
    ],
)
def test_the_baseline_profile_is_the_kind_with_nothing_optional_set(
    kind: DeploymentKind, auth_mode: AuthMode
) -> None:
    baseline = baseline_profile(kind)
    deployment_profile.cache_clear()

    assert baseline == deployment_profile(
        kind,
        auth_mode,
        unlimited_usage=False,
        local_code_sandbox=False,
        blob_store=None,
    )


def test_the_baseline_profile_is_the_memoised_unconfigured_profile() -> None:
    assert baseline_profile(DeploymentKind.PRODUCTION) is deployment_profile(
        DeploymentKind.PRODUCTION,
        "workos",
        unlimited_usage=False,
        local_code_sandbox=False,
        blob_store=None,
    )
