"""The capability table: what each deployment must set, pinned to what each one boots with today."""

from pydantic.fields import FieldInfo
import pytest

from app.config.capability_requirements import required_keys, unused_keys
from app.config.deployment import DeploymentKind, baseline_profile
from app.config.settings import ProductionSettings, SelfHostSettings


def _required_fields(fields: dict[str, FieldInfo]) -> set[str]:
    return {name for name, field in fields.items() if field.is_required()}


def test_production_requires_exactly_what_the_table_says() -> None:
    assert required_keys(baseline_profile(DeploymentKind.PRODUCTION)) == _required_fields(
        ProductionSettings.model_fields
    ) | {"WORKOS_API_KEY", "WORKOS_CLIENT_ID", "WORKOS_COOKIE_PASSWORD"}


def test_selfhost_requires_exactly_what_the_table_says() -> None:
    assert required_keys(baseline_profile(DeploymentKind.SELFHOST)) == _required_fields(
        SelfHostSettings.model_fields
    )


def test_a_selfhost_instance_that_stores_files_in_cloudinary_needs_its_credentials() -> None:
    from app.config.deployment import BlobStoreKind, deployment_profile

    profile = deployment_profile(
        DeploymentKind.SELFHOST,
        "local",
        unlimited_usage=False,
        local_code_sandbox=False,
        blob_store=BlobStoreKind.CLOUDINARY,
    )

    assert {"CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"} <= (
        required_keys(profile)
    )


@pytest.mark.parametrize("kind", list(DeploymentKind))
def test_a_key_is_never_both_required_and_unused(kind: DeploymentKind) -> None:
    profile = baseline_profile(kind)

    assert required_keys(profile).isdisjoint(unused_keys(profile))
