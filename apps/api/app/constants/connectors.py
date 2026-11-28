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
# The env var the REST helper reads the secret from.
CONNECTOR_REST_SECRET_ENV: Final = "GAIA_CONNECTOR_SECRET"

# How the HIL gate keys a connector call's remembered approval.
CONNECTOR_HIL_KEY_PREFIX: Final = "connector:"
# The command type every SDK script call shares: a script cannot be classified.
SDK_SCRIPT_COMMAND_TYPE: Final = "script"
