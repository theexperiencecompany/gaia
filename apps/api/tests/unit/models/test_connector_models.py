"""The connector spec refuses what GAIA could not install safely or bind honestly."""

from pydantic import ValidationError
import pytest

from app.models.connector_models import ConnectorSpec, InstallPackage, PackageManager
from tests.factories import make_connector_spec


@pytest.mark.parametrize("version", ["latest", "^1.2.0", ">=2", "1.x || 2.x"])
def test_an_unpinned_version_is_refused(version: str) -> None:
    with pytest.raises(ValidationError):
        InstallPackage(manager=PackageManager.NPM, name="vercel", version=version)


def test_a_binary_needs_https_and_its_checksum() -> None:
    with pytest.raises(ValidationError, match="https"):
        InstallPackage(
            manager=PackageManager.BINARY,
            name="gh",
            version="2.0.0",
            url="http://x/gh",
            sha256="a" * 64,
        )
    with pytest.raises(ValidationError, match="sha256"):
        InstallPackage(
            manager=PackageManager.BINARY, name="gh", version="2.0.0", url="https://x/gh"
        )


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


@pytest.mark.parametrize(
    "cosmetic",
    [
        {"capability": "Different words"},
        {"usage": {"guidance": "Use --json for machine output."}},
        {
            "credential": {
                "env": ["GH_TOKEN"],
                "label": "Token",
                "token_url": "https://github.com/x",
            }
        },
    ],
)
def test_the_trust_fingerprint_ignores_what_only_the_card_or_the_model_reads(
    cosmetic: dict[str, object],
) -> None:
    assert (
        make_connector_spec("cli").trust_fingerprint()
        == make_connector_spec("cli", **cosmetic).trust_fingerprint()
    )


@pytest.mark.parametrize(
    "change",
    [
        {"allowed_hosts": ["api.github.com", "github.com", "uploads.github.com"]},
        {"risk": {"read_commands": ["api", "repo list", "issue list", "issue create"]}},
        {"risk": {"read_commands": ["api", "repo list", "issue list"], "write_flags": []}},
        {"command": "hub"},
        {"credential": {"env": ["GITHUB_TOKEN"]}},
        {
            "credential": {
                "env": ["GH_TOKEN"],
                "files": [{"path": "~/.config/gh/x", "template": "{secret}"}],
            }
        },
        {"verify": {"args": ["auth", "status"]}},
        {"install": [{"manager": "npm", "name": "gh", "version": "1.0.0"}]},
    ],
)
def test_the_trust_fingerprint_changes_with_anything_that_runs_or_routes_the_key(
    change: dict[str, object],
) -> None:
    assert (
        make_connector_spec("cli").trust_fingerprint()
        != make_connector_spec("cli", **change).trust_fingerprint()
    )


def test_the_trust_fingerprint_changes_with_the_rest_base_url() -> None:
    base = make_connector_spec("rest", allowed_hosts=["api.resend.com", "eu.resend.com"])
    moved = make_connector_spec(
        "rest",
        allowed_hosts=["api.resend.com", "eu.resend.com"],
        rest={"base_url": "https://eu.resend.com"},
    )

    assert base.trust_fingerprint() != moved.trust_fingerprint()


def test_a_rest_base_url_must_be_on_an_allowed_host() -> None:
    with pytest.raises(ValidationError, match="base_url"):
        make_connector_spec("rest", rest={"base_url": "https://collector.example.com"})


def test_a_rest_base_url_may_sit_under_a_wildcard_host() -> None:
    spec = make_connector_spec("rest", allowed_hosts=["*.resend.com"])

    assert spec.rest is not None and spec.rest.base_url == "https://api.resend.com"


@pytest.mark.parametrize(
    "path",
    [
        "~/.profile",
        "~/.bashrc",
        "~/.bash_profile",
        "~/.gitconfig",
        "~/token",
        "~/.local/bin/gh",
        "~/.local/lib/python3.12/site-packages/x.pth",
        "~/.gaia-connector/gaia_rest.py",
    ],
)
def test_a_credential_file_may_not_be_a_file_a_shell_or_interpreter_runs(path: str) -> None:
    with pytest.raises(ValidationError):
        make_connector_spec(
            "cli", credential={"files": [{"path": path, "template": "token={secret}"}]}
        )


@pytest.mark.parametrize(
    "path", ["~/.config/gh/hosts.yml", "~/.aws/credentials", "~/.netrc", "~/.npmrc"]
)
def test_a_credential_file_may_be_a_cli_config_file(path: str) -> None:
    spec = make_connector_spec(
        "cli", credential={"files": [{"path": path, "template": "token={secret}"}]}
    )

    assert spec.credential.files[0].path == path


def test_an_unknown_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        ConnectorSpec.model_validate({**make_connector_spec("cli").model_dump(), "shell": "sh -c"})


def _binary(arch: str) -> dict[str, str]:
    return {
        "manager": "binary",
        "name": "terraform",
        "version": "1.17.2",
        "arch": arch,
        "url": f"https://releases.hashicorp.com/terraform_1.17.2_linux_{arch}.zip",
        "sha256": "a" * 64,
        "archive_member": "terraform",
    }


def test_a_saved_binary_built_for_one_cpu_still_loads_and_names_the_missing_build() -> None:
    spec = make_connector_spec("cli", install=[_binary("amd64")])

    assert spec.missing_builds() == {"terraform": ["arm64"]}


def test_a_binary_built_for_both_cpus_is_accepted() -> None:
    spec = make_connector_spec("cli", install=[_binary("amd64"), _binary("arm64")])

    assert {p.arch for p in spec.install} == {"amd64", "arm64"}
    assert spec.missing_builds() == {}
