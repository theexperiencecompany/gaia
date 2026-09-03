"""Configuration for CLI-backed integrations.

A CLI integration is described entirely by data: what to install, what the
resulting command is called, and how that command logs in. No provider-specific
behaviour lives in code — the same three fields drive ``gh``, ``link-cli``,
``wrangler`` and a CLI nobody here has seen, which is the point. Vendor CLIs
agree on almost nothing (flag spelling, output shape, where config lands), so
the only durable contract we lean on is the one every one of them honours:
``HOME`` decides where credentials go, and an exit code says whether the tool
considers itself logged in.

The three auth shapes below are exhaustive for every CLI surveyed (GitHub,
Vercel, Cloudflare, Supabase, Stripe, Railway, Stripe Link):

``device``
    The CLI prints instructions — a URL and usually a short code — and polls
    the vendor until the human approves. GAIA never parses that output; it is
    relayed to the user verbatim and ``verify_command`` decides when the login
    landed. Nothing to keep in sync when a vendor rewords its prompt.

``token``
    The human pastes a token. It is written into the CLI's own durable HOME as
    an environment file the launcher sources, so the credential lives exactly
    where that CLI's config lives and GAIA stores none of it. A CLI that also
    wants to materialise its own config (``gh auth login --with-token``) sets
    ``login_command`` too.

``none``
    No credentials (a formatter, a local-only tool).

Browser logins that require a ``localhost`` callback are deliberately absent:
the sandbox is a different machine from the user's browser, so that redirect
can never complete. Such CLIs are configured with ``token`` instead, which
every one of them also supports.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.url_safety import assert_safe_url_shape

# An executable name, not a path. This becomes a filename in the launcher
# directory and is interpolated into shell, so it is restricted to characters
# that are inert in both roles. Vendor CLIs are all named well within this
# (`gh`, `link-cli`, `wrangler`, `supabase`).
COMMAND_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")

# Environment-variable name, for the token auth shape.
ENV_VAR_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")


# Where a connect attempt stands. Lives beside the config rather than in the
# service that drives it, because the API schema also needs it and a schema
# cannot import a service -- which is why it was previously written out twice
# and would have silently rejected a new phase at serialization time.
CliConnectPhase = Literal["installing", "needs_token", "awaiting_approval", "connected", "failed"]


class CliAuthSpec(BaseModel):
    """How one CLI authenticates."""

    kind: Literal["none", "device", "token"]

    # Shell command that performs the login. Runs through the integration's
    # launcher, so HOME/PATH/XDG are already pointed at this CLI's own dirs.
    #
    # For ``device`` this is the command that prints the URL and polls; it is
    # run detached because it blocks for minutes and sandbox commands are
    # serialised per user (a foreground poll would freeze every other tool
    # call for that user).
    # If it takes its own polling timeout, set that at or above
    # ``LOGIN_TIMEOUT_SECONDS``: a shorter one leaves a window where the CLI
    # has stopped polling but GAIA still shows the code as live.
    #
    # For ``token`` it is optional: when set it runs once with the pasted
    # secret available under ``token_env``; when unset, exporting that variable
    # on every invocation IS the authentication.
    login_command: str | None = None

    # Exits 0 if and only if the CLI considers itself authenticated. This is
    # the single source of truth for connection state — not a parsed string,
    # not a file we look for. Every surveyed CLI has one (`gh auth status`,
    # `link-cli auth status`, `wrangler whoami`).
    verify_command: str

    # Undoes the login. Optional: when absent, disconnecting falls back to
    # deleting the CLI's durable HOME, which logs out any CLI by construction.
    logout_command: str | None = None

    # --- token shape only ---
    # Variable the pasted secret is exported as. Vendor-native names
    # (CLOUDFLARE_API_TOKEN, VERCEL_TOKEN) mean many CLIs need no
    # ``login_command`` at all.
    token_env: str | None = None
    # What to call the secret in the UI, and where the user gets one.
    token_label: str | None = None
    token_help_url: str | None = None

    @field_validator("token_env")
    @classmethod
    def _validate_token_env(cls, v: str | None) -> str | None:
        if v is not None and not ENV_VAR_RE.match(v):
            raise ValueError(f"token_env {v!r} is not a valid environment variable name")
        return v

    @model_validator(mode="after")
    def _enforce_shape_invariants(self) -> "CliAuthSpec":
        """Pin each auth shape to the fields it actually needs.

        Without this a ``token`` spec missing ``token_env`` would surface as a
        connect flow that collects a secret and silently drops it.
        """
        if self.kind == "device" and not self.login_command:
            raise ValueError("auth.kind='device' requires login_command")
        if self.kind == "token":
            if not self.token_env:
                raise ValueError("auth.kind='token' requires token_env")
            if not self.token_label:
                raise ValueError("auth.kind='token' requires token_label for the UI prompt")
        if self.kind == "none" and self.login_command:
            raise ValueError("auth.kind='none' must not set login_command")
        return self


class CliConfig(BaseModel):
    """Everything GAIA needs to run one third-party CLI on a user's behalf."""

    # The executable the agent invokes, e.g. "link-cli". A launcher of this
    # name is generated on PATH; the agent never sees an absolute path.
    command: str

    # Shell that installs the CLI. Runs unprivileged, in this integration's
    # own local-disk app directory, with the baked Node runtime on PATH.
    # Deliberately a free-form command rather than a package name: npm,
    # a release tarball, and a vendor install script are all one line here,
    # and a CLI distributed some fourth way needs no code change.
    install_command: str

    # Human-readable summary of what this CLI is for, shown on the integration
    # card. The agent gets the real detail from the CLI's own --help.
    capabilities: list[str] = Field(default_factory=list)

    # The vendor's own site, used only to fetch the icon shown on the
    # integration card. Declared rather than derived: the obvious shortcut is to
    # reuse a URL out of ``install_command``, but that names where the bytes are
    # hosted, not whose tool this is. A CLI published through GitHub Releases or
    # npm would take GitHub's or npm's icon, which looks plausible and is wrong.
    homepage: str | None = None

    auth: CliAuthSpec

    @field_validator("homepage")
    @classmethod
    def _validate_homepage(cls, v: str | None) -> str | None:
        """Reject anything the favicon fetcher should not be pointed at.

        This value reaches an outbound HTTP request, and for an agent-authored
        integration it originates from a model, so it gets the same cheap
        SSRF shape check the MCP server URL does.
        """
        if v is None or not v.strip():
            return None
        assert_safe_url_shape(v)
        return v

    @property
    def requires_auth(self) -> bool:
        """Whether connecting this CLI needs a credential step.

        One derived predicate instead of ``auth.kind != "none"`` spelled out at
        every call site, so adding a fourth auth shape cannot leave one of them
        behind.
        """
        return self.auth.kind != "none"

    @field_validator("command")
    @classmethod
    def _validate_command(cls, v: str) -> str:
        if not COMMAND_NAME_RE.match(v):
            raise ValueError(
                f"command {v!r} must be a bare executable name "
                "(letters, digits, dot, dash, underscore)"
            )
        return v

    @field_validator("install_command")
    @classmethod
    def _validate_install(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("install_command cannot be empty")
        return v
