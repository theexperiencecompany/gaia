"""The coding agents' home in the sandbox: fast local disk, saved to JuiceFS so nothing is lost.

Claude Code and OpenCode keep logins, sessions and work under ~/agents (an
OpenCode turn took ~2.5 min with its data on JuiceFS and ~10s locally,
measured). gaia-save packs the home into one archive under /workspace/agents
before every event a CLI reports and on each keep-warm tick; a fresh sandbox
unpacks it.
"""

import base64
from collections.abc import Mapping
import json
from pathlib import Path
import shlex
from typing import Final

from app.constants.sandbox import SANDBOX_USER_HOME
from app.utils.errors import AppError

AGENTS_HOME: Final[str] = f"{SANDBOX_USER_HOME}/agents"
AGENTS_SAVE: Final[str] = "/workspace/agents"
AGENTS_WORK_DIR: Final[str] = f"{AGENTS_HOME}/work"
AGENTS_RUNS_DIR: Final[str] = f"{AGENTS_HOME}/runs"
SAVE_ARCHIVE: Final[str] = f"{AGENTS_SAVE}/home.tgz"
SAVED_AT_FILE: Final[str] = f"{AGENTS_SAVE}/.saved_at"

_BIN_DIR: Final[str] = f"{AGENTS_HOME}/bin"
_CONFIG_DIR: Final[str] = f"{AGENTS_HOME}/config"
_STATE_DIR: Final[str] = f"{AGENTS_HOME}/state"
SAVE_SCRIPT: Final[str] = f"{_BIN_DIR}/gaia-save"
HOOK_SCRIPT: Final[str] = f"{_BIN_DIR}/gaia-hook"
CLAUDE_SETTINGS_PATH: Final[str] = f"{_CONFIG_DIR}/claude-settings.json"
OPENCODE_CONFIG_DIR: Final[str] = f"{_CONFIG_DIR}/opencode"
CLAUDE_CONFIG_DIR: Final[str] = f"{_STATE_DIR}/claude"
_OPENCODE_DATA_DIR: Final[str] = f"{_STATE_DIR}/opencode"
_OPENCODE_DATA_LINK: Final[str] = f"{SANDBOX_USER_HOME}/.local/share/opencode"
_OPENCODE_DB: Final[str] = f"{_OPENCODE_DATA_DIR}/opencode.db"
# The archive carries this consistent copy; a restore puts it back as the database.
_OPENCODE_DB_SNAPSHOT: Final[str] = f"{_OPENCODE_DB}.snapshot"
_PLUGIN_PATH: Final[str] = f"{OPENCODE_CONFIG_DIR}/plugins/gaia_notify.js"
_PROFILE: Final[str] = f"{SANDBOX_USER_HOME}/.profile"
# Present once this sandbox's home is set up; absent on a fresh sandbox, which restores.
_READY_MARKER: Final[str] = f"{AGENTS_HOME}/.ready"

#: Rebuildable folders a save skips; a restored sandbox reinstalls them.
SAVE_EXCLUDES: Final[tuple[str, ...]] = (
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".cache",
    ".next",
    ".turbo",
    "target",
    ".pytest_cache",
    ".mypy_cache",
)
SAVE_TIMEOUT_SECONDS: Final[int] = 120
# Save, then up to two 15s POSTs (the event, and a failed save's report).
HOOK_TIMEOUT_SECONDS: Final[int] = SAVE_TIMEOUT_SECONDS + 30
#: A restore copies the whole saved home back from JuiceFS.
AGENTS_SETUP_TIMEOUT_SECONDS: Final[int] = 300

#: Printed by the setup command when it restored a fresh sandbox from the save.
RESTORED_MARKER: Final[str] = "restored_from="

_PROFILE_BEGIN: Final[str] = "# >>> gaia agents >>>"
_PROFILE_END: Final[str] = "# <<< gaia agents <<<"
# Every login shell (GAIA's bash tool runs bash -l) finds both CLIs and Claude's state.
_PROFILE_BLOCK: Final[str] = (
    f"{_PROFILE_BEGIN}\n"
    'export PATH="$HOME/.local/bin:$HOME/.opencode/bin:$PATH"\n'
    f"export CLAUDE_CONFIG_DIR={shlex.quote(CLAUDE_CONFIG_DIR)}\n"
    f"{_PROFILE_END}\n"
)

_VENDORED: Final[Path] = Path(__file__).parent


def render_vendored(filename: str, values: Mapping[str, str]) -> str:
    """Render a vendored file's {{NAME}} placeholders; fails loud when one is missing or left over."""
    text = (_VENDORED / filename).read_text()
    for name, value in values.items():
        placeholder = f"{{{{{name}}}}}"
        if placeholder not in text:
            raise AppError(
                message="vendored sandbox file is missing a placeholder",
                why=f"{placeholder} not found in {filename}",
                fix="restore the placeholder; agents_home.py documents the contract",
                status_code=500,
                code="agent_lab_vendored_drift",
            )
        text = text.replace(placeholder, value)
    if "{{" in text:
        raise AppError(
            message="vendored sandbox file has an unrendered placeholder",
            why=f"{filename} still contains '{{{{' after rendering",
            fix="pass every placeholder the file declares",
            status_code=500,
            code="agent_lab_vendored_drift",
        )
    return text


def claude_hook_settings() -> str:
    """Return Claude's --settings: each way a turn ends or waits runs gaia-hook once.

    StopFailure is the API-error stop (expired login, rate limit) that Stop
    never fires for. One matcherless group per event, so an event relays once.
    """
    handler = {"type": "command", "command": HOOK_SCRIPT, "timeout": HOOK_TIMEOUT_SECONDS}
    events = ("Stop", "StopFailure", "Notification")
    return json.dumps({"hooks": {event: [{"hooks": [handler]}] for event in events}})


def _rendered_files() -> dict[str, str]:
    """Return every per-sandbox file the setup writes, keyed by sandbox path."""
    hook_values = {"GAIA_HOOK": HOOK_SCRIPT, "HOOK_TIMEOUT_SECONDS": str(HOOK_TIMEOUT_SECONDS)}
    return {
        SAVE_SCRIPT: render_vendored(
            "gaia_save.sh",
            {
                "AGENTS_HOME": AGENTS_HOME,
                "SAVE_ARCHIVE": SAVE_ARCHIVE,
                "DB_SNAPSHOT": _OPENCODE_DB_SNAPSHOT,
                "SAVE_EXCLUDES": " ".join(shlex.quote(name) for name in SAVE_EXCLUDES),
                "SAVED_AT_FILE": SAVED_AT_FILE,
            },
        ),
        HOOK_SCRIPT: render_vendored(
            "gaia_hook.sh",
            {"SAVE_SCRIPT": SAVE_SCRIPT, "SAVE_TIMEOUT_SECONDS": str(SAVE_TIMEOUT_SECONDS)},
        ),
        CLAUDE_SETTINGS_PATH: claude_hook_settings(),
        _PLUGIN_PATH: render_vendored("opencode_notify_plugin.js", hook_values),
    }


def write_file_step(path: str, content: str, *, append: bool = False) -> str:
    """Return a shell step writing (or appending) content to path; base64 keeps quoting out of it."""
    encoded = base64.b64encode(content.encode()).decode()
    return f"echo '{encoded}' | base64 -d {'>>' if append else '>'} {shlex.quote(path)}"


def build_agents_setup_command() -> str:
    """Return the idempotent per-sandbox setup: restore a fresh sandbox, then lay out ~/agents.

    Restores only when this sandbox has no home yet and a save exists, printing
    RESTORED_MARKER with the save's timestamp so the caller can report it.
    """
    home = shlex.quote(AGENTS_HOME)
    archive = shlex.quote(SAVE_ARCHIVE)
    snapshot = shlex.quote(_OPENCODE_DB_SNAPSHOT)
    restore = (
        f"if [ ! -e {shlex.quote(_READY_MARKER)} ] && [ -f {archive} ]; then"
        f" mkdir -p {home} && tar -xzf {archive} -C {home}"
        f" && if [ -f {snapshot} ]; then mv -f {snapshot} {shlex.quote(_OPENCODE_DB)}; fi"
        f" && echo {RESTORED_MARKER}$(cat {shlex.quote(SAVED_AT_FILE)} 2>/dev/null); fi"
    )
    dirs = " ".join(
        shlex.quote(d)
        for d in (
            AGENTS_WORK_DIR,
            AGENTS_RUNS_DIR,
            _BIN_DIR,
            CLAUDE_CONFIG_DIR,
            _OPENCODE_DATA_DIR,
            f"{OPENCODE_CONFIG_DIR}/plugins",
            f"{SANDBOX_USER_HOME}/.local/share",
        )
    )
    link = shlex.quote(_OPENCODE_DATA_LINK)
    profile = shlex.quote(_PROFILE)
    steps = [
        restore,
        f"mkdir -p {dirs}",
        f"chmod 700 {home}",
        *(write_file_step(path, content) for path, content in _rendered_files().items()),
        f"chmod 700 {shlex.quote(SAVE_SCRIPT)} {shlex.quote(HOOK_SCRIPT)}",
        # Relink only a link or nothing; a real data dir from a manual login is left alone.
        f"if [ -L {link} ] || [ ! -e {link} ]; then ln -sfn {shlex.quote(_OPENCODE_DATA_DIR)} {link}; fi",
        # Replace our block, keep the rest; awk, as the run seed also runs on BSD userland in tests.
        f"touch {profile}",
        f"awk -v b={shlex.quote(_PROFILE_BEGIN)} -v e={shlex.quote(_PROFILE_END)}"
        f" '$0==b{{skip=1}} !skip{{print}} $0==e{{skip=0}}' {profile} > {profile}.gaia-tmp",
        f"mv -f {profile}.gaia-tmp {profile}",
        write_file_step(_PROFILE, _PROFILE_BLOCK, append=True),
        f"touch {shlex.quote(_READY_MARKER)}",
    ]
    return " && ".join(steps)


def restored_from(setup_output: str) -> str | None:
    """Return the save timestamp the setup restored from, or None when it restored nothing."""
    for line in setup_output.splitlines():
        if line.startswith(RESTORED_MARKER):
            return line[len(RESTORED_MARKER) :] or "unknown"
    return None
