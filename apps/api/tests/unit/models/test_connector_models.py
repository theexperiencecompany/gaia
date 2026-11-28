"""The connector spec refuses what GAIA could not install safely or bind honestly."""

from pydantic import ValidationError
import pytest

from app.models.connector_models import ConnectorSpec, InstallPackage
from tests.factories import make_connector_spec


@pytest.mark.parametrize("version", ["latest", "^1.2.0", ">=2", "1.x || 2.x"])
def test_an_unpinned_version_is_refused(version: str) -> None:
    with pytest.raises(ValidationError):
        InstallPackage(manager="npm", name="vercel", version=version)


def test_a_binary_needs_https_and_its_checksum() -> None:
    with pytest.raises(ValidationError, match="https"):
        InstallPackage(
            manager="binary", name="gh", version="2.0.0", url="http://x/gh", sha256="a" * 64
        )
    with pytest.raises(ValidationError, match="sha256"):
        InstallPackage(manager="binary", name="gh", version="2.0.0", url="https://x/gh")


def test_a_rest_connector_takes_its_key_in_the_auth_slot_not_env() -> None:
    with pytest.raises(ValidationError, match="rest.auth"):
        make_connector_spec("rest", credential={"env": ["RESEND_API_KEY"]})


def test_a_cli_connector_must_bind_the_secret_somewhere() -> None:
    with pytest.raises(ValidationError, match="bind the secret"):
        make_connector_spec("cli", credential={"env": []})


def test_a_credential_file_must_hold_the_placeholder_and_stay_under_home() -> None:
    with pytest.raises(ValidationError):
        make_connector_spec("cli", credential={"files": [{"path": "~/.x", "template": "token"}]})
    with pytest.raises(ValidationError):
        make_connector_spec(
            "cli", credential={"files": [{"path": "~/../etc/x", "template": "{secret}"}]}
        )


def test_hosts_outside_the_provider_domain_are_named() -> None:
    spec = make_connector_spec(
        "cli", allowed_hosts=["api.github.com", "uploads.github.com", "evil.example.com"]
    )

    assert spec.hosts_outside_provider() == ["evil.example.com"]


def test_a_lookalike_domain_is_outside_the_provider() -> None:
    spec = make_connector_spec("cli", allowed_hosts=["notgithub.com"])

    assert spec.hosts_outside_provider() == ["notgithub.com"]


def test_the_reach_fingerprint_changes_with_hosts_or_packages_only() -> None:
    base = make_connector_spec("sdk")
    reworded = make_connector_spec("sdk", capability="Different words")
    new_host = make_connector_spec("sdk", allowed_hosts=["api.openai.com", "files.openai.com"])
    new_version = make_connector_spec(
        "sdk", install=[{"manager": "pip", "name": "openai", "version": "2.0.0"}]
    )

    assert base.reach_fingerprint() == reworded.reach_fingerprint()
    assert base.reach_fingerprint() != new_host.reach_fingerprint()
    assert base.reach_fingerprint() != new_version.reach_fingerprint()


def test_an_unknown_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        ConnectorSpec.model_validate({**make_connector_spec("cli").model_dump(), "shell": "sh -c"})
