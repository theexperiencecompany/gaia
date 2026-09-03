"""Filesystem layout and tunables for CLI-backed integrations.

A CLI integration runs a real third-party command-line tool (``gh``,
``link-cli``, ``wrangler``, …) inside the user's E2B sandbox. Three kinds of
bytes are involved and they must NOT share a filesystem — the split below is
the single most important decision in this subsystem, and it is measured, not
assumed:

===================  ====================  ====================================
What                 Where                 Why
===================  ====================  ====================================
Language runtime     ``RUNTIME_DIR``       Baked into the E2B template. Node is
                     (image, local disk)   188 MB / ~20k files. Extracting it
                                           onto JuiceFS took >600 s and left
                                           ``node`` with a 12 s startup; from
                                           the image it is 0.3 s.
Installed CLI        ``APPS_DIR``          Local disk, re-created per sandbox.
packages             (local disk)          ``npm install @stripe/link-cli`` is
                                           ~20 s here and effectively unbounded
                                           on JuiceFS (thousands of small
                                           files). Losing it on sandbox
                                           recreation is the correct trade: a
                                           20 s reinstall beats a 10 min mount.
Credentials +        ``home_dir()``        JuiceFS — durable across pause,
CLI config           (JuiceFS)             kill, and recreation. This is a
                                           handful of small files (a token
                                           JSON, a hosts.yml), which JuiceFS
                                           serves fine, and it is the ONLY part
                                           that must survive: losing it would
                                           log the user out of every CLI.
===================  ====================  ====================================

The CLI is pointed at its durable config by ``HOME`` (plus the XDG variables
for tools that honour them), set by the per-app launcher in ``LAUNCHER_DIR``.
GAIA therefore stores no CLI credential itself — the tool owns its own login,
exactly as it would on a laptop — and a CLI we have never seen keeps working
as long as it respects ``HOME``.
"""

import hashlib
from typing import Final

from app.agents.workspace.paths import GAIA_RUNTIME_DIRNAME, WORKSPACE_ROOT
from app.constants.sandbox import (
    BASH_DEFAULT_TIMEOUT_SECONDS,
    BASH_MAX_COMMAND_LENGTH,
    BASH_MAX_TIMEOUT_SECONDS,
)

# --- Local disk (baked into the image or re-created per sandbox) -------------

# Language runtime baked into the template, under a root only the build writes.
# Only Node today: it is what the overwhelming majority of vendor CLIs ship on
# (npm), and Go/Rust CLIs distribute self-contained binaries that need no
# toolchain to *run*.
GAIA_OPT_ROOT = "/opt/gaia"
RUNTIME_DIR = f"{GAIA_OPT_ROOT}/runtime"
RUNTIME_BIN_DIR = f"{RUNTIME_DIR}/bin"

# Installs and launchers live under the sandbox user's OWN home, not under
# /opt, so nothing here depends on the template having pre-created a directory.
# That is not tidiness: E2B resumes a paused sandbox from its original image, so
# after a template change a returning user can keep running on the old
# filesystem for hours. Rooting these at a path the unprivileged user always
# owns means such a sandbox installs cleanly instead of failing on
# "mkdir: /opt/gaia: Permission denied". (A missing Node still fails, but with
# "npm: not found", which says what to do.)
#
# Local disk, like /opt: re-created per sandbox by design. Only credentials are
# durable (see CLI_HOME_ROOT).
SANDBOX_USER_ROOT = "/home/user/.gaia"

# One directory per installed CLI integration, holding whatever its install
# command produced (node_modules/, an extracted release tarball, …).
APPS_DIR = f"{SANDBOX_USER_ROOT}/apps"

# Generated launcher scripts, one per installed CLI, added to PATH for every
# CLI tool invocation. Each launcher pins its own app's HOME so two CLIs can
# appear in the same shell pipeline without fighting over ~/.config.
LAUNCHER_DIR = f"{SANDBOX_USER_ROOT}/bin"

# Node version baked into the template. Pinned rather than "lts" so a rebuild
# is reproducible and a CLI that breaks on a new major does so when we choose.
NODE_VERSION = "22.14.0"
NODE_TARBALL_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-linux-x64.tar.xz"

# --- JuiceFS (durable across sandbox recreation) -----------------------------

# Parent of the per-integration HOME directories. Sits under the existing
# /workspace/.gaia runtime dir so it stays out of the user's own file tree
# (and out of `ls /workspace`), alongside .gaia/runs.
CLI_HOME_ROOT = f"{WORKSPACE_ROOT}/{GAIA_RUNTIME_DIRNAME}/apps"


def app_dir(integration_id: str) -> str:
    """Local-disk directory holding this integration's installed CLI."""
    return f"{APPS_DIR}/{integration_id}"


def home_dir(integration_id: str) -> str:
    """Durable (JuiceFS) HOME for this integration's CLI — where its login lives."""
    return f"{CLI_HOME_ROOT}/{integration_id}"


def launcher_path(command: str) -> str:
    """Path of the generated launcher that puts ``command`` on PATH."""
    return f"{LAUNCHER_DIR}/{command}"


def install_marker_path(integration_id: str) -> str:
    """Marker written after a successful install, read to skip reinstalling.

    Lives beside the install on LOCAL disk, so a recreated sandbox correctly
    reports "not installed" and reinstalls, while a warm one skips the ~20 s.
    """
    return f"{app_dir(integration_id)}/.gaia-installed"


# --- Tunables ---------------------------------------------------------------

# Install is a one-off cold cost (npm install of a vendor CLI measured at ~20 s;
# a release-tarball download at ~1 s). The ceiling is generous because it is
# paid once per sandbox, never per call.
INSTALL_TIMEOUT_SECONDS = 600

# A single CLI invocation on behalf of the agent. These ARE sandbox shell
# commands, so they take the sandbox's bounds rather than a second copy of the
# same two numbers (constants/sandbox.py asks callers to import instead of
# redefining, and a constant whose comment says "matches X" is a copy of X).
EXEC_DEFAULT_TIMEOUT_SECONDS: Final[int] = BASH_DEFAULT_TIMEOUT_SECONDS
EXEC_MAX_TIMEOUT_SECONDS: Final[int] = BASH_MAX_TIMEOUT_SECONDS

# Bound on a "does this CLI consider itself logged in?" probe. Kept short: it
# runs on every connect poll, and a CLI that cannot answer in this window is
# reported as not-yet-authenticated rather than blocking the poll.
VERIFY_TIMEOUT_SECONDS = 60

# How long a device-code login may stay pending before the connect flow gives
# up and starts a fresh one. Vendor device codes typically expire in 5–15
# minutes; 600s sits inside that for every CLI surveyed.
#
# An integration's own login command must not stop polling BEFORE this window
# elapses. The gap between the two is time in which the CLI has given up but
# GAIA still believes the login is live, so the user is shown a code that can
# no longer be redeemed. Keep a polling login command's timeout at or above
# this value.
LOGIN_TIMEOUT_SECONDS = 600

# Maximum characters of captured CLI output surfaced in a connect status
# response. Login output is instructions for a human ("go to <url>, enter
# <code>"), never a transcript, so this is ample.
LOGIN_OUTPUT_MAX_CHARS = 4_000


# --- The agent-facing tool ---------------------------------------------------

# Metadata stamped on every CLI-backed tool. Lives here rather than beside the
# tool factory because the HIL gate reads it, and a service importing an
# agent-tool module would drag langchain, e2b and the sandbox client into the
# gate's import graph.
CLI_INTEGRATION_METADATA_KEY = "gaia_cli_integration"
CLI_COMMAND_METADATA_KEY = "gaia_cli_command"

# Custom integrations are per-user Mongo documents, but the tool registry is
# process-global and keyed by name alone ("Tool names are globally unique" --
# registry.py). Two users each authoring a CLI called `gh` would therefore
# collide: last writer wins, and the loser's approval cards, Chroma namespace
# and cached HIL verdict all resolve to the other user's integration. A short
# digest of the integration id keeps the name readable and unique.
_CUSTOM_TOOL_NAME_DIGEST_CHARS = 8


def cli_tool_name(command: str, integration_id: str, *, is_platform: bool) -> str:
    """The registry name for one CLI integration's tool.

    Platform integrations keep the clean ``run_<command>`` form: their ids are
    curated and unique, so there is nothing to disambiguate. Custom ones carry a
    digest of their integration id.
    """
    base = f"run_{command.replace('-', '_').replace('.', '_')}"
    if is_platform:
        return base
    digest = hashlib.sha256(integration_id.encode()).hexdigest()
    return f"{base}_{digest[:_CUSTOM_TOOL_NAME_DIGEST_CHARS]}"


# A CLI invocation is a shell string like any other, so it takes the same length
# bound the bash tool applies. Without it the CLI tool accepted an unbounded
# command its sibling refuses.
EXEC_MAX_COMMAND_LENGTH: Final[int] = BASH_MAX_COMMAND_LENGTH
