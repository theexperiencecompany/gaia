"""A connector: any CLI, REST API or SDK GAIA runs with the user's key, described as data.

CLI, REST and SDK are presets of one spec. Each call runs in a fresh runner that
holds the credential for that one call (see app/services/connectors/).
"""

from enum import StrEnum
import hashlib
import re
from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from app.constants.connectors import (
    CONNECTOR_GUIDANCE_MAX_CHARS,
    CONNECTOR_SECRET_PLACEHOLDER,
    CONNECTOR_SECRET_PLACEHOLDERS,
    CONNECTOR_SECRET_USER_PLACEHOLDER,
    CREDENTIAL_DENIED_DIRS,
    CREDENTIAL_HOME_FILES,
    MAX_CONNECTOR_HOSTS,
    MAX_CONNECTOR_PACKAGES,
)

_HOST_RE = re.compile(r"^(\*\.)?([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
_PINNED_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}$")
_COMMAND_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DNS_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)
# Stands in for the account when a host template is checked against allowed_hosts at define time.
_SAMPLE_ACCOUNT = "account"
_WILDCARD = "*."
# Fields only the connect card or the model reads; changing them moves no key and runs nothing new.
_COSMETIC_FIELDS: dict[str, bool | set[str]] = {
    "capability": True,
    "usage": True,
    "credential": {"label", "token_url"},
}


def host_allowed(host: str, allowed_hosts: list[str]) -> bool:
    """Say whether a host is listed; "*.x.com" covers subdomains only, as E2B's allowlist does."""
    return any(
        host.endswith(pattern.removeprefix("*"))
        if pattern.startswith(_WILDCARD)
        else host == pattern
        for pattern in allowed_hosts
    )


class InvalidConnectorKeyError(ValueError):
    """Raised when a pasted key cannot fill the spec's slots, e.g. its account half is not a DNS label."""


class ConnectorKind(StrEnum):
    CLI = "cli"
    REST = "rest"
    SDK = "sdk"


class PackageManager(StrEnum):
    NPM = "npm"
    PIP = "pip"
    BINARY = "binary"
    APT = "apt"


class CpuArch(StrEnum):
    AMD64 = "amd64"
    ARM64 = "arm64"


class CredentialKind(StrEnum):
    API_KEY = "api_key"
    OAUTH = "oauth"


class SdkRuntime(StrEnum):
    PYTHON = "python"
    NODE = "node"


class InstallPackage(BaseModel):
    """One pinned package the runner installs before the call; a binary is checksummed."""

    model_config = ConfigDict(extra="forbid")

    manager: PackageManager
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9@/._-]+$")
    version: str = Field(description="Exact version; ranges are refused")
    url: str | None = Field(default=None, description="Binary: https URL of the archive or file")
    sha256: str | None = Field(default=None, description="Binary: SHA-256 of the downloaded file")
    archive_member: str | None = Field(
        default=None,
        description="Binary inside a .tar.gz/.zip: path of the executable within it",
        pattern=r"^[A-Za-z0-9._/-]+$",
    )
    arch: CpuArch | None = Field(
        default=None,
        description="Binary: the CPU it is built for; list one package per arch (cloud is amd64)",
    )

    @field_validator("version")
    @classmethod
    def _pinned(cls, value: str) -> str:
        if not _PINNED_VERSION_RE.fullmatch(value) or value.lower() == "latest":
            raise ValueError(f"version must be one exact version, got {value!r}")
        return value

    @model_validator(mode="after")
    def _binary_is_verifiable(self) -> Self:
        if self.manager is PackageManager.BINARY:
            if not self.url or not self.url.startswith("https://"):
                raise ValueError("a binary package needs an https url")
            if not self.sha256 or not _SHA256_RE.fullmatch(self.sha256):
                raise ValueError("a binary package needs its lowercase hex sha256")
        elif self.url or self.sha256 or self.archive_member or self.arch:
            raise ValueError("url, sha256 and archive_member apply to binary packages only")
        return self


class CredentialFile(BaseModel):
    """A config file the runner writes before the call; the template holds the secret placeholder."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^~/[A-Za-z0-9._/-]+$",
        description="Path under the runner's home, starting with ~/",
    )
    template: str = Field(min_length=1, max_length=4000)

    @field_validator("template")
    @classmethod
    def _has_placeholder(cls, value: str) -> str:
        if not any(placeholder in value for placeholder in CONNECTOR_SECRET_PLACEHOLDERS):
            raise ValueError(
                f"template must contain one of {', '.join(CONNECTOR_SECRET_PLACEHOLDERS)}"
            )
        return value

    @field_validator("path")
    @classmethod
    def _config_location(cls, value: str) -> str:
        parts = value.removeprefix("~/").split("/")
        if ".." in parts:
            raise ValueError("path may not contain ..")
        if len(parts) == 1:
            if parts[0] not in CREDENTIAL_HOME_FILES:
                raise ValueError(
                    f"a home file must be one of {sorted(CREDENTIAL_HOME_FILES)}; "
                    "put other config in its tool's dot-directory, e.g. ~/.config/<tool>/"
                )
        elif not parts[0].startswith(".") or parts[0] in CREDENTIAL_DENIED_DIRS:
            raise ValueError(
                f"path must be in a tool's dot-directory other than {sorted(CREDENTIAL_DENIED_DIRS)}"
            )
        return value


class CredentialBinding(BaseModel):
    """Where the user's secret goes in the runner, and where the user gets one."""

    model_config = ConfigDict(extra="forbid")

    kind: CredentialKind = CredentialKind.API_KEY
    env: list[str] = Field(default_factory=list, max_length=4)
    files: list[CredentialFile] = Field(default_factory=list, max_length=4)
    label: str = Field(default="API key", min_length=1, max_length=60)
    token_url: str | None = Field(
        default=None, description="https page where the user creates the key (the card's deep link)"
    )

    @field_validator("env")
    @classmethod
    def _env_names(cls, value: list[str]) -> list[str]:
        for name in value:
            if not _ENV_NAME_RE.fullmatch(name):
                raise ValueError(f"invalid environment variable name {name!r}")
        return value

    @field_validator("token_url")
    @classmethod
    def _https(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("https://"):
            raise ValueError("token_url must be https")
        return value


class UsageDocs(BaseModel):
    """What activation loads into the agent's context."""

    model_config = ConfigDict(extra="forbid")

    help_args: list[str] = Field(default_factory=lambda: ["--help"], max_length=6)
    json_flag: str | None = Field(default=None, max_length=40)
    guidance: str = Field(default="", max_length=CONNECTOR_GUIDANCE_MAX_CHARS)


class RiskRules(BaseModel):
    """Which calls read. Anything not proven a read is a write, and asks once per command type."""

    model_config = ConfigDict(extra="forbid")

    read_commands: list[str] = Field(
        default_factory=list,
        max_length=60,
        description='CLI subcommand prefixes that only read, e.g. "repo list", "api"',
    )
    write_flags: list[str] = Field(
        default_factory=list,
        max_length=20,
        description='Flags that make any command a write, e.g. "-X", "--method"',
    )


class IdentityExtractor(BaseModel):
    """How the verify call's stdout names the account: a JSON dot path, else a regex group."""

    model_config = ConfigDict(extra="forbid")

    json_path: str | None = Field(default=None, max_length=120, pattern=r"^[A-Za-z0-9_.\-]+$")
    regex: str | None = Field(default=None, max_length=200)

    @field_validator("regex")
    @classmethod
    def _compiles(cls, value: str | None) -> str | None:
        if value is not None:
            if re.compile(value).groups < 1:
                raise ValueError("regex needs one capture group naming the account")
        return value


class VerifySpec(BaseModel):
    """A read-only call proving the credential works, and where its output names the account."""

    model_config = ConfigDict(extra="forbid")

    args: list[str] = Field(min_length=1, max_length=20)
    identity: IdentityExtractor = Field(default_factory=IdentityExtractor)


class RestConfig(BaseModel):
    """REST preset: GAIA's request helper fixes the base URL, so the key only reaches its host."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(
        min_length=9,
        max_length=200,
        description=(
            f"May start its host with {CONNECTOR_SECRET_USER_PLACEHOLDER}, the account half of a key "
            f"pasted as ID:SECRET, e.g. https://{CONNECTOR_SECRET_USER_PLACEHOLDER}-dsn.algolia.net"
        ),
    )
    auth_header: str | None = Field(
        default="Authorization", max_length=60, pattern=r"^[A-Za-z0-9-]+$"
    )
    auth_template: str = Field(default=f"Bearer {CONNECTOR_SECRET_PLACEHOLDER}", max_length=200)
    auth_query_param: str | None = Field(default=None, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
    account_header: str | None = Field(
        default=None,
        max_length=60,
        pattern=r"^[A-Za-z0-9-]+$",
        description="A header that carries the account half of an ID:SECRET key",
    )

    @field_validator("base_url")
    @classmethod
    def _https_base(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("base_url must be https")
        first_label, _, rest = value.removeprefix("https://").partition(".")
        if "{" in rest or "{" in first_label.replace(CONNECTOR_SECRET_USER_PLACEHOLDER, "", 1):
            raise ValueError(
                f"base_url takes only {CONNECTOR_SECRET_USER_PLACEHOLDER}, once, in its host's first label"
            )
        return value.rstrip("/")

    @property
    def uses_account(self) -> bool:
        """Say whether a call needs the account half of an ID:SECRET key."""
        return CONNECTOR_SECRET_USER_PLACEHOLDER in self.base_url or self.account_header is not None

    def base_url_for(self, account: str) -> str:
        """Fill the host template with an account, refused unless it is one DNS label."""
        if not _DNS_LABEL_RE.fullmatch(account):
            raise InvalidConnectorKeyError(
                "the account part of the key (before the colon) must be one DNS label: "
                "letters, digits and inner hyphens"
            )
        return self.base_url.replace(CONNECTOR_SECRET_USER_PLACEHOLDER, account.lower())

    @model_validator(mode="after")
    def _one_auth_slot(self) -> Self:
        if (self.auth_header is None) == (self.auth_query_param is None):
            raise ValueError("set exactly one of auth_header or auth_query_param")
        return self


class ConnectorSpec(BaseModel):
    """Everything GAIA needs to install, authenticate, run, classify and verify one connector."""

    model_config = ConfigDict(extra="forbid")

    kind: ConnectorKind
    provider_domain: str = Field(description="The provider's own registrable domain, e.g. fly.io")
    capability: str = Field(
        min_length=1, max_length=140, description="One line: what GAIA can do with it"
    )
    command: str | None = Field(
        default=None, description="CLI: the executable the args run against"
    )
    sdk_runtime: SdkRuntime | None = None
    rest: RestConfig | None = None
    install: list[InstallPackage] = Field(default_factory=list, max_length=MAX_CONNECTOR_PACKAGES)
    credential: CredentialBinding = Field(default_factory=CredentialBinding)
    usage: UsageDocs = Field(default_factory=UsageDocs)
    risk: RiskRules = Field(default_factory=RiskRules)
    allowed_hosts: list[str] = Field(min_length=1, max_length=MAX_CONNECTOR_HOSTS)
    verify: VerifySpec

    @field_validator("provider_domain")
    @classmethod
    def _domain(cls, value: str) -> str:
        value = value.lower().strip()
        if value.startswith("*.") or not _HOST_RE.fullmatch(value):
            raise ValueError(f"invalid provider domain {value!r}")
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def _hosts(cls, value: list[str]) -> list[str]:
        hosts = [host.lower().strip() for host in value]
        for host in hosts:
            if not _HOST_RE.fullmatch(host):
                raise ValueError(f"invalid host {host!r}")
        return sorted(set(hosts))

    @model_validator(mode="after")
    def _preset_shape(self) -> Self:
        match self.kind:
            case ConnectorKind.CLI:
                if not self.command or not _COMMAND_RE.fullmatch(self.command):
                    raise ValueError("a cli connector names its executable in command")
                if self.rest or self.sdk_runtime:
                    raise ValueError("a cli connector takes no rest or sdk_runtime")
            case ConnectorKind.REST:
                if self.rest is None or self.command or self.sdk_runtime:
                    raise ValueError("a rest connector takes rest and nothing else")
                if self.credential.env or self.credential.files:
                    raise ValueError("a rest connector's key goes in rest.auth_*, not env/files")
                base_host = urlsplit(self.rest.base_url_for(_SAMPLE_ACCOUNT)).hostname or ""
                if not host_allowed(base_host, self.allowed_hosts):
                    raise ValueError(f"rest.base_url's host {base_host!r} must be in allowed_hosts")
            case ConnectorKind.SDK:
                if self.sdk_runtime is None or self.command or self.rest:
                    raise ValueError("an sdk connector takes sdk_runtime and nothing else")
        if self.kind is not ConnectorKind.REST and not (
            self.credential.env or self.credential.files
        ):
            raise ValueError("bind the secret to at least one env var or file")
        return self

    def rest_base_url(self, account: str) -> str:
        """Return the base URL a call goes to for this account, refused when it leaves allowed_hosts."""
        if self.rest is None:
            raise ValueError("only a rest connector has a base URL")
        url = self.rest.base_url_for(account)
        host = urlsplit(url).hostname or ""
        if not host_allowed(host, self.allowed_hosts):
            raise InvalidConnectorKeyError(
                f"the key's account makes a host, {host!r}, outside allowed_hosts"
            )
        return url

    def missing_builds(self) -> dict[str, list[str]]:
        """Name each binary with no build for some runner CPU: cloud runs amd64, self-host may be arm64.

        Checked where a connector is defined, never on load, so a saved one stays readable.
        """
        builds: dict[str, set[CpuArch]] = {}
        for package in self.install:
            if package.manager is PackageManager.BINARY and package.arch is not None:
                builds.setdefault(package.name, set()).add(package.arch)
        return {
            name: sorted(arch.value for arch in set(CpuArch) - arches)
            for name, arches in builds.items()
            if set(CpuArch) - arches
        }

    def hosts_outside_provider(self) -> list[str]:
        """Return the allowed hosts that are not the provider's domain or one of its subdomains."""
        domain = self.provider_domain
        return [
            host
            for host in self.allowed_hosts
            if host.removeprefix("*.") != domain
            and not host.removeprefix("*.").endswith(f".{domain}")
        ]

    def trust_fingerprint(self) -> str:
        """Hash everything a user's approval covers: what runs with the key and where it goes."""
        canonical = self.model_dump_json(exclude=_COSMETIC_FIELDS)
        return hashlib.sha256(canonical.encode()).hexdigest()


class ConnectorCardInfo(BaseModel):
    """What a connector's connect card shows before the user hands over a key."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    kind: ConnectorKind
    capability: str
    provider_domain: str
    # Every host the key can reach; the card lists them verbatim.
    allowed_hosts: list[str]
    key_label: str
    token_url: str | None = None
    verified: bool = False

    @classmethod
    def from_spec(cls, spec: ConnectorSpec, *, verified: bool) -> "ConnectorCardInfo":
        return cls(
            kind=spec.kind,
            capability=spec.capability,
            provider_domain=spec.provider_domain,
            allowed_hosts=spec.allowed_hosts,
            key_label=spec.credential.label,
            token_url=spec.credential.token_url,
            verified=verified,
        )
