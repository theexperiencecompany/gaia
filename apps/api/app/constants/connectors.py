"""Connector constants: the spec's limits, the runner's bounds, and the tool names."""

from typing import Final

MANAGED_BY_CONNECTOR: Final = "connector"

RUN_CONNECTOR_TOOL: Final = "run_connector"
DEFINE_CONNECTOR_TOOL: Final = "define_connector"

# The placeholder a credential file or REST auth template holds where the secret goes.
CONNECTOR_SECRET_PLACEHOLDER: Final = "{secret}"

CONNECTOR_GUIDANCE_MAX_CHARS: Final = 2000
MAX_CONNECTOR_HOSTS: Final = 12
MAX_CONNECTOR_PACKAGES: Final = 6
MAX_CONNECTOR_ARGS: Final = 64
MAX_CONNECTOR_ARG_CHARS: Final = 20_000

# One call's wall clock inside the runner, and the install's before it.
CONNECTOR_CALL_TIMEOUT_SECONDS: Final = 90
CONNECTOR_INSTALL_TIMEOUT_SECONDS: Final = 240
# The throwaway E2B sandbox's own lifetime: install + call + slack, then E2B kills it.
CONNECTOR_SANDBOX_LIFETIME_SECONDS: Final = 420

# What reaches the model of one call's stdout and stderr, after scrubbing.
CONNECTOR_STDOUT_HEAD_BYTES: Final = 24 * 1024
CONNECTOR_STDOUT_TAIL_BYTES: Final = 6 * 1024
CONNECTOR_STDERR_HEAD_BYTES: Final = 4 * 1024
CONNECTOR_STDERR_TAIL_BYTES: Final = 2 * 1024
# What the runner keeps of a stream before scrubbing; past it the call is cut short.
CONNECTOR_RAW_OUTPUT_MAX_BYTES: Final = 8 * 1024 * 1024

CONNECTOR_REDACTION: Final = "[REDACTED]"

# Hosts the install phase may reach, per package manager. The call phase reaches
# only the spec's allowed_hosts.
NPM_REGISTRY_HOSTS: Final = ("registry.npmjs.org",)
NODE_DIST_HOSTS: Final = ("nodejs.org",)
PIP_REGISTRY_HOSTS: Final = ("pypi.org", "files.pythonhosted.org")
APT_REGISTRY_HOSTS: Final = (
    "deb.debian.org",
    "security.debian.org",
    "archive.ubuntu.com",
    "security.ubuntu.com",
)

# Where the runner keeps GAIA's own helpers (the REST request helper), under its home.
CONNECTOR_HELPER_DIR: Final = "~/.gaia-connector"
CONNECTOR_REST_HELPER: Final = f"{CONNECTOR_HELPER_DIR}/gaia_rest.py"
# A credential file lives in its tool's own dot-directory (~/.config/gh/hosts.yml) or is one of
# these home files. Other home paths may be read as code: ~/.profile by the runner's login
# shell, ~/.local by python's site and PATH, the helper dir by GAIA itself.
CREDENTIAL_HOME_FILES: Final = frozenset({".netrc", ".npmrc", ".pypirc"})
CREDENTIAL_DENIED_DIRS: Final = frozenset({".local", CONNECTOR_HELPER_DIR.removeprefix("~/")})
# Where a binary download host redirects to: a GitHub release asset is served from these.
BINARY_REDIRECT_HOSTS: Final[dict[str, tuple[str, ...]]] = {
    "github.com": ("objects.githubusercontent.com", "release-assets.githubusercontent.com"),
}
# Where a binary package's executable is installed, on the runner's PATH.
CONNECTOR_BINARY_DIR: Final = "/usr/local/bin"

# The Node every npm package runs on, on both runners: an LTS from nodejs.org, unpacked into
# /usr/local over whatever the base image ships (E2B's base has 20.9). The sha256 per
# nodejs.org arch name is from the release's signed SHASUMS256.txt.
CONNECTOR_NODE_VERSION: Final = "24.22.3"
CONNECTOR_NODE_SHA256: Final[dict[str, str]] = {
    "x64": "061ec3e3062115705b56b51fa9cc330ab50d34b6969387d4e4b1a50c6809acc2",
    "arm64": "261af2af250dfd7e9f25cf151d1b2713a0adf8f10a9ad116c4947f68627affe8",
}
CONNECTOR_NODE_PREFIX: Final = "/usr/local"

# E2B's plain base image (Debian, python3, node, npm, curl), not the user workspace template.
CONNECTOR_E2B_TEMPLATE: Final = "base"
CONNECTOR_E2B_PURPOSE: Final = "connector"

# Self-host: one throwaway container per call, from an image with the install baked in.
CONNECTOR_DOCKER_IMAGE_REPOSITORY: Final = "gaia-connector"
CONNECTOR_DOCKER_CONTAINER_PREFIX: Final = "gaia-connector-"
CONNECTOR_DOCKER_LABEL: Final = "gaia.connector"
# Not the API's uid: a call's container shares no files with the host.
CONNECTOR_DOCKER_USER: Final = "1000:1000"
CONNECTOR_DOCKER_MEMORY_LIMIT: Final = "1g"
CONNECTOR_DOCKER_CPUS: Final = "1"
CONNECTOR_DOCKER_PIDS_LIMIT: Final = 256

# Self-host egress: each call gets its own internal network with no route out, and one
# allowlisting forward proxy (CONNECT to the spec's hosts only, no TLS interception) as
# its only way out. Canonical's ubuntu/squid:7.2-26.04_stable, pinned by its index digest.
CONNECTOR_EGRESS_PROXY_IMAGE: Final = (
    "ubuntu/squid@sha256:51e524f1b8c72b5ce15c288ba0b1618771cee09dc1a317b0dd7d81dc4f441312"
)
CONNECTOR_EGRESS_PROXY_BINARY: Final = "/usr/sbin/squid-gnutls"
CONNECTOR_EGRESS_PROXY_PORT: Final = 3128
CONNECTOR_EGRESS_PROXY_MEMORY_LIMIT: Final = "256m"
CONNECTOR_EGRESS_PROXY_PIDS_LIMIT: Final = 64

CONNECTOR_NO_SANDBOX_MESSAGE: Final = (
    "Connectors need a code sandbox: add an E2B key or run `gaia up --code-sandbox`"
)

# How the HIL gate keys a connector call's remembered approval.
CONNECTOR_HIL_KEY_PREFIX: Final = "connector:"
# The command type every SDK script call shares: a script cannot be classified.
SDK_SCRIPT_COMMAND_TYPE: Final = "script"
