"""Run a third-party CLI inside the user's sandbox.

This module owns the only place GAIA knows anything mechanical about CLI
integrations: where a CLI is installed, how it is put on ``PATH``, and how its
credentials are pointed at durable storage. Everything provider-specific
arrives as data in :class:`~app.models.cli_config.CliConfig`.

Three invariants shape the code.

**Installs are ephemeral, logins are not.** The sandbox is recreated roughly
hourly, taking the installed package with it, while the CLI's credentials live
on JuiceFS and survive. Every entry point therefore re-installs on demand
rather than assuming a prior call did — the guard is a single ``test -f`` folded
into the same shell invocation, so a warm sandbox pays nothing (measured 2.2 s
for a full CLI call) and a cold one self-heals instead of reporting "command
not found" (27 s for an npm-based CLI, 4.5 s for a release tarball).

**One round trip per operation.** Sandbox commands are serialised per user, so
each extra round trip is latency every other tool call for that user waits on.
The install guard, the install itself, the launcher generation and the actual
work all ride in one script; :func:`probe_state` answers every question the
connect flow asks in a single call.

**The CLI is the source of truth for its own login.** GAIA never parses login
output and never stores a vendor credential in its own database. Connection
state is whatever ``verify_command`` exits with, which is the only signal that
stays correct when a token is revoked, expires, or is rotated outside GAIA.
"""

from __future__ import annotations

from dataclasses import dataclass
import shlex

from e2b import AsyncSandbox, CommandExitException

from app.agents.workspace.paths import WORKSPACE_ROOT
from app.constants.cli_integrations import (
    APPS_DIR,
    CLI_HOME_ROOT,
    GAIA_OPT_ROOT,
    INSTALL_TIMEOUT_SECONDS,
    LAUNCHER_DIR,
    LOGIN_OUTPUT_MAX_CHARS,
    RUNTIME_BIN_DIR,
    SANDBOX_USER_ROOT,
    VERIFY_TIMEOUT_SECONDS,
    app_dir,
    home_dir,
    install_marker_path,
    launcher_path,
)
from app.constants.log_tags import LogTag
from app.models.cli_config import CliConfig
from shared.py.wide_events import log

# Exit code the install guard uses to say "install ran and failed". Chosen
# outside the range a vendor CLI realistically returns so an install failure is
# never mistaken for the user's command exiting non-zero.
INSTALL_FAILED_EXIT_CODE = 111

# Where the install script's own output goes, so it never contaminates the
# output of the command the agent actually asked for. Read back verbatim when
# an install fails, which is the only time anyone wants it.
_INSTALL_LOG = "install.log"

# A device login blocks for minutes while the human approves in a browser, and
# sandbox commands are serialised per user — running it in the foreground would
# freeze every other tool call for that user for the whole window. It is
# therefore detached, with its output and pid on local disk beside the install.
_LOGIN_LOG = "login.log"
_LOGIN_PID = "login.pid"

# Environment file inside the CLI's durable HOME, sourced by the launcher.
# Holds token-shaped credentials for CLIs whose authentication *is* an
# environment variable. Lives with that CLI's own config rather than in a GAIA
# table, so "log out" and "delete the app" are the same operation.
_ENV_FILE = ".gaia-env"

# Markers framing the structured block probe_state() parses. Chosen to be
# inert in shell and absent from any plausible CLI output.
_STATE_LINE = "__GAIA_CLI_STATE__"
_OUTPUT_BEGIN = "__GAIA_CLI_OUTPUT_BEGIN__"


@dataclass(frozen=True)
class CliResult:
    """Outcome of one CLI invocation."""

    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def install_failed(self) -> bool:
        return self.exit_code == INSTALL_FAILED_EXIT_CODE


@dataclass(frozen=True)
class CliState:
    """Everything the connect flow needs, read from the sandbox in one call.

    Deliberately derived rather than stored: the sandbox filesystem and the
    CLI's own exit code already hold this state, so there is no second copy to
    fall out of sync when a sandbox is recreated or a token is revoked
    upstream.
    """

    installed: bool
    authenticated: bool
    login_running: bool
    # Seconds since the detached login started, or ``None`` if none has been
    # started in this sandbox. Read from the login log's mtime so it needs no
    # external bookkeeping.
    login_age_seconds: int | None
    # The login command's own output, verbatim — the URL and code a human needs.
    login_output: str
    # Populated only when the install itself failed, so the connect flow can
    # say why instead of "connection failed".
    install_error: str = ""


# Roots that exist only because GAIA runs the CLI in a sandbox. A vendor CLI
# routinely echoes where it put its config; that path is meaningful to a
# developer on a laptop and meaningless (and confusing) to a user who never
# asked for a sandbox. Lines mentioning one are dropped before the output is
# shown, which is a presentation rule about OUR paths, not an attempt to parse
# the vendor's text.
_INTERNAL_PATH_ROOTS = (WORKSPACE_ROOT, SANDBOX_USER_ROOT, GAIA_OPT_ROOT)


def user_visible_output(text: str) -> str:
    """Strip lines that expose GAIA's own sandbox paths, keeping the rest verbatim."""
    kept = [
        line for line in text.splitlines() if not any(root in line for root in _INTERNAL_PATH_ROOTS)
    ]
    return "\n".join(kept).strip()


def _bin_search_path(integration_id: str) -> str:
    """PATH fragment covering every layout an install command might produce.

    npm drops binaries in ``node_modules/.bin``; release tarballs use ``bin/``;
    ``pip install --user`` and friends use ``.local/bin``; a bare ``curl`` of a
    single binary lands in the app dir itself. Searching all four means the
    config never has to declare a layout.
    """
    app = app_dir(integration_id)
    return ":".join(
        [
            f"{app}/node_modules/.bin",
            f"{app}/bin",
            f"{app}/.local/bin",
            app,
            RUNTIME_BIN_DIR,
        ]
    )


def _launcher_body(integration_id: str) -> str:
    """The generated launcher, minus the shebang and resolved-binary binding.

    Those two lines are prepended by the install script, which is the only
    place the resolved binary path is known.

    Every CLI invocation goes through this. It is what makes credentials
    durable (``HOME`` on JuiceFS) and what lets two different CLIs appear in
    the same pipeline without fighting over ``~/.config`` — each one's launcher
    pins its own environment only for the duration of that exec.
    """
    home = home_dir(integration_id)
    return f"""# Generated by GAIA for the {integration_id!r} CLI integration. Do not edit:
# rewritten on every (re)install.
export HOME={shlex.quote(home)}
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_STATE_HOME="$HOME/.local/state"
export XDG_CACHE_HOME="$HOME/.cache"
# Credentials for CLIs whose auth is an environment variable (written by the
# token connect flow). Absent for device-login CLIs, which keep their own
# config under $HOME instead.
if [ -f "$HOME/{_ENV_FILE}" ]; then . "$HOME/{_ENV_FILE}"; fi
export PATH={shlex.quote(_bin_search_path(integration_id))}:"$PATH"
exec "$GAIA_CLI_BINARY" "$@"
"""


def _install_script(integration_id: str, config: CliConfig) -> str:
    """Idempotent install: no-op when warm, full install when cold.

    Written as one script rather than orchestrated from Python so a cold call
    costs the same single round trip as a warm one.
    """
    app = app_dir(integration_id)
    marker = install_marker_path(integration_id)
    launcher = launcher_path(config.command)
    log_path = f"{app}/{_INSTALL_LOG}"
    # HOME during install points at LOCAL disk, not the durable JuiceFS home:
    # installers write caches (npm's ~/.npm is hundreds of files) that would be
    # pathologically slow on JuiceFS and are worthless to persist.
    install_home = f"{app}/.home"

    return f"""
gaia_install() {{
  mkdir -p {shlex.quote(app)} {shlex.quote(install_home)} \\
           {shlex.quote(home_dir(integration_id))} {shlex.quote(LAUNCHER_DIR)} || return 1
  (
    set -e
    cd {shlex.quote(app)}
    export HOME={shlex.quote(install_home)}
    export PATH={shlex.quote(RUNTIME_BIN_DIR)}:"$PATH"
    {config.install_command}
  ) >{shlex.quote(log_path)} 2>&1 || return 1

  # Resolve what the install actually produced rather than requiring the config
  # to declare a path — npm, tarballs and single-binary downloads all differ.
  gaia_bin=$(PATH={shlex.quote(_bin_search_path(integration_id))} \\
             command -v {shlex.quote(config.command)} 2>/dev/null) || return 1
  [ -n "$gaia_bin" ] || return 1

  # Two-part emit: the resolved binary must be expanded by THIS shell, while
  # the body must not be (it contains $HOME, $PATH and $@ for the launcher's
  # own runtime). A quoted heredoc for the body keeps those literal.
  {{
    printf '#!/bin/sh\\n'
    printf "GAIA_CLI_BINARY='%s'\\n" "$gaia_bin"
    cat <<'GAIA_LAUNCHER_EOF'
{_launcher_body(integration_id)}
GAIA_LAUNCHER_EOF
  }} > {shlex.quote(launcher)} || return 1
  chmod 0755 {shlex.quote(launcher)} || return 1
  touch {shlex.quote(marker)} || return 1
}}

if [ ! -f {shlex.quote(marker)} ] || [ ! -x {shlex.quote(launcher)} ]; then
  if ! gaia_install; then
    echo "gaia: failed to install {config.command}" >&2
    tail -40 {shlex.quote(log_path)} >&2 2>/dev/null
    exit {INSTALL_FAILED_EXIT_CODE}
  fi
fi
"""


def _wrap(integration_id: str, config: CliConfig, command: str) -> str:
    """Install guard + the caller's command, sharing one shell.

    ``PATH`` carries the launcher directory and the Node runtime, so the
    caller's command names the CLI exactly as a human would (``link-cli auth
    status``), and shell features — pipes, redirection, ``&&`` — work normally.
    """
    return (
        f"{_install_script(integration_id, config)}\n"
        f'export PATH={shlex.quote(f"{LAUNCHER_DIR}:{RUNTIME_BIN_DIR}")}:"$PATH"\n'
        f"{command}\n"
    )


async def _run(
    sbx: AsyncSandbox, script: str, *, timeout: int, cwd: str | None = None
) -> CliResult:
    """Execute a prepared script, normalising e2b's non-zero-exit exception."""
    try:
        result = await sbx.commands.run(script, timeout=timeout, cwd=cwd)
        return CliResult(
            exit_code=result.exit_code or 0,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )
    except CommandExitException as e:
        # A non-zero exit is a normal outcome for a CLI (not logged in, no such
        # resource); the SDK raises rather than returning, so translate it back.
        return CliResult(exit_code=e.exit_code, stdout=e.stdout or "", stderr=e.stderr or "")


def _login_log_path(integration_id: str) -> str:
    return f"{app_dir(integration_id)}/{_LOGIN_LOG}"


def _login_pid_path(integration_id: str) -> str:
    return f"{app_dir(integration_id)}/{_LOGIN_PID}"


async def execute(
    sbx: AsyncSandbox,
    integration_id: str,
    config: CliConfig,
    command: str,
    *,
    timeout: int,
    cwd: str | None = None,
) -> CliResult:
    """Run a shell command with this integration's CLI available on PATH."""
    return await _run(sbx, _wrap(integration_id, config, command), timeout=timeout, cwd=cwd)


async def ensure_installed(sbx: AsyncSandbox, integration_id: str, config: CliConfig) -> CliResult:
    """Install the CLI if this sandbox does not already have it.

    Safe to call on every request: warm sandboxes short-circuit on a marker
    file. Returns the outcome so a caller can surface *why* an install failed.
    """
    result = await _run(
        sbx, _install_script(integration_id, config), timeout=INSTALL_TIMEOUT_SECONDS
    )
    if not result.ok:
        log.warning(
            f"{LogTag.INTEGRATION} CLI install failed",
            integration_id=integration_id,
            command=config.command,
            exit_code=result.exit_code,
        )
    return result


async def probe_state(sbx: AsyncSandbox, integration_id: str, config: CliConfig) -> CliState:
    """Every fact the connect flow needs, in one sandbox round trip.

    Installs on demand first (so a recreated sandbox reports honestly rather
    than "not authenticated"), then answers three questions at once: does the
    CLI consider itself logged in, is a detached login still polling, and what
    has that login printed for the user.
    """
    script = _wrap(
        integration_id,
        config,
        f"""
gaia_authed=0
if ( {config.auth.verify_command} ) >/dev/null 2>&1; then gaia_authed=1; fi

gaia_running=0
gaia_pid=$(cat {shlex.quote(_login_pid_path(integration_id))} 2>/dev/null || true)
if [ -n "$gaia_pid" ] && kill -0 "$gaia_pid" 2>/dev/null; then gaia_running=1; fi

gaia_age=-1
if [ -f {shlex.quote(_login_log_path(integration_id))} ]; then
  gaia_now=$(date +%s)
  gaia_mtime=$(stat -c %Y {shlex.quote(_login_log_path(integration_id))} 2>/dev/null || echo "$gaia_now")
  gaia_age=$((gaia_now - gaia_mtime))
fi

echo "{_STATE_LINE} authenticated=$gaia_authed running=$gaia_running age=$gaia_age"
echo "{_OUTPUT_BEGIN}"
cat {shlex.quote(_login_log_path(integration_id))} 2>/dev/null || true
""",
        # The verify command is the slow part (a network round trip to the
        # vendor); everything else is local.
    )
    # The install guard rides inside this same shell, and a cold sandbox is
    # exactly the state probe_state is called in (advance calls it first). A
    # verify-sized budget here would kill the install that has to finish before
    # the verify can mean anything.
    result = await _run(sbx, script, timeout=INSTALL_TIMEOUT_SECONDS + VERIFY_TIMEOUT_SECONDS)

    if result.install_failed:
        return CliState(
            installed=False,
            authenticated=False,
            login_running=False,
            login_age_seconds=None,
            login_output="",
            install_error=user_visible_output(result.stderr)[:LOGIN_OUTPUT_MAX_CHARS],
        )
    return _parse_state(result.stdout)


def _parse_state(stdout: str) -> CliState:
    """Read the structured block emitted by :func:`probe_state`'s script."""
    flags: dict[str, str] = {}
    output_lines: list[str] = []
    in_output = False
    for line in stdout.splitlines():
        if in_output:
            output_lines.append(line)
        elif line.startswith(_STATE_LINE):
            flags = dict(part.split("=", 1) for part in line.split()[1:] if "=" in part)
        elif line.startswith(_OUTPUT_BEGIN):
            in_output = True

    age = int(flags.get("age", "-1"))
    return CliState(
        # Reaching the state line at all means the install guard passed.
        installed=bool(flags),
        authenticated=flags.get("authenticated") == "1",
        login_running=flags.get("running") == "1",
        login_age_seconds=None if age < 0 else age,
        login_output=user_visible_output("\n".join(output_lines))[:LOGIN_OUTPUT_MAX_CHARS],
    )


async def start_login(sbx: AsyncSandbox, integration_id: str, config: CliConfig) -> CliResult:
    """Launch a device login detached, and return as soon as it is running.

    The CLI's own instructions ("open <url> and enter <code>") land in a log
    that :func:`probe_state` reads back verbatim. GAIA deliberately does not
    parse them: every vendor words this differently and rewords it between
    releases, so relaying the tool's own text is both more robust and more
    honest to the user than a guessed-at URL.
    """
    if not config.auth.login_command:  # pragma: no cover - forbidden by validator
        raise ValueError(f"{integration_id}: device login without login_command")

    log_path = _login_log_path(integration_id)
    pid_path = _login_pid_path(integration_id)
    detached = (
        f"rm -f {shlex.quote(log_path)} {shlex.quote(pid_path)}; "
        f"nohup sh -c {shlex.quote(config.auth.login_command)} "
        f"> {shlex.quote(log_path)} 2>&1 & "
        f"echo $! > {shlex.quote(pid_path)}"
    )
    return await _run(sbx, _wrap(integration_id, config, detached), timeout=INSTALL_TIMEOUT_SECONDS)


async def cancel_login(sbx: AsyncSandbox, integration_id: str) -> None:
    """Stop an in-flight device login and forget its output."""
    pid_path = _login_pid_path(integration_id)
    await _run(
        sbx,
        f"gaia_pid=$(cat {shlex.quote(pid_path)} 2>/dev/null || true); "
        f'if [ -n "$gaia_pid" ]; then kill "$gaia_pid" 2>/dev/null || true; fi; '
        f"rm -f {shlex.quote(pid_path)} {shlex.quote(_login_log_path(integration_id))}; true",
        timeout=30,
    )


async def write_token(
    sbx: AsyncSandbox, integration_id: str, config: CliConfig, token: str
) -> CliResult:
    """Persist a pasted secret into the CLI's own durable HOME.

    Written as a shell env file the launcher sources, so the credential sits
    with that CLI's other config and is removed by the same "delete the app
    directory" that logs it out. Written with ``sbx.files.write`` rather than a
    shell command so the secret never appears in argv or shell history.
    """
    env_var = config.auth.token_env
    if not env_var:  # pragma: no cover - forbidden by CliAuthSpec's validator
        raise ValueError(f"{integration_id}: token auth without token_env")

    # The install both creates the durable HOME and generates the launcher that
    # will source this file, so it must land first.
    installed = await ensure_installed(sbx, integration_id, config)
    if not installed.ok:
        return installed

    path = f"{home_dir(integration_id)}/{_ENV_FILE}"
    await sbx.files.write(path, f"export {env_var}={shlex.quote(token)}\n")
    # 0600: the sandbox is single-tenant, but a credential file should still not
    # be readable by anything the agent later runs under another identity.
    await _run(sbx, f"chmod 0600 {shlex.quote(path)}", timeout=30)

    if not config.auth.login_command:
        # Exporting the variable *is* the authentication; nothing further to run.
        return CliResult(exit_code=0, stdout="", stderr="")
    return await execute(
        sbx, integration_id, config, config.auth.login_command, timeout=INSTALL_TIMEOUT_SECONDS
    )


async def clear_credentials(sbx: AsyncSandbox, integration_id: str, config: CliConfig) -> None:
    """Log the CLI out and remove its durable state.

    Runs the declared ``logout_command`` when there is one — some vendors
    revoke the token server-side, which deleting a local file does not — and
    then removes the durable HOME regardless, so disconnect is complete even
    for a CLI that offers no logout at all.
    """
    if config.auth.logout_command:
        await execute(
            sbx,
            integration_id,
            config,
            # A CLI that is already logged out exits non-zero here; that is not
            # a failure of the disconnect, so it never blocks the wipe below.
            f"{config.auth.logout_command} || true",
            timeout=INSTALL_TIMEOUT_SECONDS,
        )
    await _run(
        sbx,
        "rm -rf "
        f"{shlex.quote(home_dir(integration_id))} "
        f"{shlex.quote(app_dir(integration_id))} "
        f"{shlex.quote(launcher_path(config.command))}",
        timeout=120,
    )


def workspace_roots() -> tuple[str, str, str]:
    """The three directories this subsystem owns, for diagnostics and tests."""
    return APPS_DIR, LAUNCHER_DIR, CLI_HOME_ROOT
