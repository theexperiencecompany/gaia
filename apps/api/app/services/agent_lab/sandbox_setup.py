"""Per-RUN sandbox seeding for Agent Lab: hooks fragment + plugin + credential links.

The vendored ``claude_hooks.json`` is a template, not a live config. Its two
placeholders are rendered per run at lab start — never hardcoded, so no
host or credential is baked into the repo or the template:

- ``{{GAIA_LAB_EVENTS_URL}}`` → ``SANDBOX_LAB_EVENTS_CALLBACK_URL`` (the
  /api/v1/lab/events URL reachable FROM the E2B sandbox, public API base).
- ``{{GAIA_LAB_TOKEN}}`` → a per-run HMAC token minted by
  :func:`mint_lab_hooks_token` (same scheme as /sandbox/execute, but with an
  EMPTY tool scope, so the token is useless on /sandbox/execute and only the
  events receiver accepts it).

Per-run isolation: EVERYTHING lands under the RUN's workdir, never the global
``~/.claude/settings.json``, so two concurrent runs keep separate tokens::

    <run_dir>/.claude/settings.json              — Claude picks up hooks, no flags
    <run_dir>/.gaia/claude-hooks.json            — auditable rendered fragment
    <run_dir>/.gaia/lab-env                      — GAIA_LAB_CALLBACK_URL/TOKEN/SESSION_ID (0600)
    <run_dir>/.opencode/plugins/gaia_lab_notify.js — vendored relay plugin

The OpenCode plugin reads its three ``GAIA_LAB_*`` vars from ``process.env``
at event time, so whatever starts ``opencode serve`` must source the env file
first (``set -a; . <run_dir>/.gaia/lab-env; set +a``) — that `serve` start is
T1's job; this module only guarantees the file exists with rendered values.
Claude needs no env: its session id arrives inside the native hook POST body,
and the receiver maps ``hook_event_name`` to kind (unmatched Notification
types become ``notification_other`` there, not here).

Reply-routing seam: the seed script ends by echoing a stable
``GAIA_LAB_RUN_ID=<session_id>`` line so the model driving the CLI via bash
has one id to reference in replies. Persisting the CLI-native session id
(``--session-id`` / ``-s``) onto the todo at start is T1's job, not this
module's.

Credential DIRS are linked (never copied) into ``/workspace/.credentials/*``
for JuiceFS persistence; linking is link-if-missing only, so a live login is
never clobbered.
"""

import base64
from pathlib import Path
from typing import Final

from app.config.settings import settings
from app.constants.execute import SANDBOX_LAB_EVENTS_TOKEN_TTL_SECONDS
from app.services.sandbox.execute_token import mint_execute_token
from app.utils.errors import AppError

URL_PLACEHOLDER: Final[str] = "{{GAIA_LAB_EVENTS_URL}}"
TOKEN_PLACEHOLDER: Final[str] = "{{GAIA_LAB_TOKEN}}"

FRAGMENT_FILENAME: Final[str] = "claude_hooks.json"
PLUGIN_FILENAME: Final[str] = "opencode_notify_plugin.js"

# Per-run layout, all relative to the RUN's workdir (never global paths).
CLAUDE_SETTINGS_REL: Final[str] = ".claude/settings.json"
SEEDED_FRAGMENT_REL: Final[str] = ".gaia/claude-hooks.json"
LAB_ENV_REL: Final[str] = ".gaia/lab-env"
PLUGIN_REL: Final[str] = ".opencode/plugins/gaia_lab_notify.js"
MERGE_SCRIPT_PATH: Final[str] = "/tmp/gaia-merge-hooks.py"

# Env keys the OpenCode relay plugin reads at event time (see PLUGIN_FILENAME).
LAB_CALLBACK_URL_VAR: Final[str] = "GAIA_LAB_CALLBACK_URL"
LAB_TOKEN_VAR: Final[str] = "GAIA_LAB_TOKEN"
LAB_SESSION_ID_VAR: Final[str] = "GAIA_LAB_SESSION_ID"
LAB_RUN_ID_VAR: Final[str] = "GAIA_LAB_RUN_ID"

# Install-if-missing, one line per CLI. The drive skills
# (lab-claude-drive, lab-opencode-drive) are the source of truth for method;
# Codex is docs-only in MVP (no relay fragment, no install line).
LOCAL_BIN_EXPORT: Final[str] = 'export PATH="/workspace/.local/bin:$PATH"'
CLAUDE_INSTALL_LINE: Final[str] = (
    "command -v claude >/dev/null 2>&1 || curl -fsSL https://claude.ai/install.sh | bash -s 2.1.286"
)
OPENCODE_INSTALL_LINE: Final[str] = (
    "command -v opencode >/dev/null 2>&1 || curl -fsSL https://opencode.ai/install | bash"
)

# Home credential dir → JuiceFS-backed target. The template owns the canonical
# links; seeding only ensures them link-if-missing at session start.
CREDENTIAL_LINKS: Final[tuple[tuple[str, str], ...]] = (
    ("$HOME/.claude", "/workspace/.credentials/claude"),
    ("$HOME/.codex", "/workspace/.credentials/codex"),
    ("$HOME/.local/share/opencode", "/workspace/.credentials/opencode"),
)

MERGE_SETTINGS_SCRIPT: Final[str] = """\
import json
import sys

fragment_path, settings_path = sys.argv[1], sys.argv[2]
with open(fragment_path) as handle:
    fragment = json.load(handle)
try:
    with open(settings_path) as handle:
        current = json.load(handle)
except FileNotFoundError:
    current = {}
hooks = current.setdefault("hooks", {})
for event, groups in fragment.get("hooks", {}).items():
    existing = hooks.setdefault(event, [])
    for group in groups:
        if group not in existing:
            existing.append(group)
with open(settings_path, "w") as handle:
    json.dump(current, handle, indent=2)
"""


def lab_events_enabled() -> bool:
    """Whether hooks can be seeded: same secret plus the sandbox-reachable URL."""
    return bool(settings.SANDBOX_EXECUTE_TOKEN_SECRET and settings.SANDBOX_LAB_EVENTS_CALLBACK_URL)


def lab_events_url() -> str:
    """Sandbox-reachable receiver URL; fails loud when unconfigured."""
    url = settings.SANDBOX_LAB_EVENTS_CALLBACK_URL
    if not url:
        raise AppError(
            message="lab lifecycle pushes are not configured",
            why="SANDBOX_LAB_EVENTS_CALLBACK_URL is unset",
            fix="set it to the public /api/v1/lab/events URL so sandbox hooks can reach GAIA",
            status_code=503,
            code="agent_lab_events_unconfigured",
        )
    return url


def mint_lab_hooks_token(user_id: str, session_id: str) -> str:
    """Per-run hooks token; empty tool scope keeps it off /sandbox/execute."""
    return mint_execute_token(
        user_id,
        session_id,
        scoped_tool_names=[],
        ttl_seconds=SANDBOX_LAB_EVENTS_TOKEN_TTL_SECONDS,
    )


def render_hooks_fragment(events_url: str, token: str) -> str:
    """Render the vendored fragment with per-run values; fails loud on drift."""
    template = Path(__file__).with_name(FRAGMENT_FILENAME).read_text()
    for placeholder in (URL_PLACEHOLDER, TOKEN_PLACEHOLDER):
        if placeholder not in template:
            raise AppError(
                message="lab hooks fragment is missing its placeholder",
                why=f"{placeholder} not found in {FRAGMENT_FILENAME}",
                fix="restore the placeholder — the seeder documents the contract",
                status_code=500,
                code="agent_lab_hooks_fragment_drift",
            )
    return template.replace(URL_PLACEHOLDER, events_url).replace(TOKEN_PLACEHOLDER, token)


def render_lab_env(events_url: str, token: str, session_id: str) -> str:
    """KEY=value lines the `serve` starter sources; fails loud on empty input."""
    if not events_url or not token or not session_id:
        raise AppError(
            message="lab env has no empty fields",
            why="events_url, token and session_id are all required",
            fix="mint the hooks token first, then render the env",
            status_code=500,
            code="agent_lab_env_incomplete",
        )
    return (
        f"{LAB_CALLBACK_URL_VAR}={events_url}\n"
        f"{LAB_TOKEN_VAR}={token}\n"
        f"{LAB_SESSION_ID_VAR}={session_id}\n"
    )


def build_seed_command(events_url: str, token: str, session_id: str, run_dir: str) -> str:
    """One idempotent shell script seeding hooks + plugin + env + links into the run workdir."""
    if not run_dir:
        raise AppError(
            message="lab seed needs a run workdir",
            why="run_dir is empty — per-run isolation has no target",
            fix="pass the run's workdir so hooks land in <run_dir>/.claude, never global",
            status_code=500,
            code="agent_lab_seed_missing_run_dir",
        )
    fragment = render_hooks_fragment(events_url, token)
    env_file = render_lab_env(events_url, token, session_id)
    plugin = Path(__file__).with_name(PLUGIN_FILENAME).read_text()
    fragment_b64 = base64.b64encode(fragment.encode()).decode()
    merge_b64 = base64.b64encode(MERGE_SETTINGS_SCRIPT.encode()).decode()
    plugin_b64 = base64.b64encode(plugin.encode()).decode()
    env_b64 = base64.b64encode(env_file.encode()).decode()
    settings_path = f"{run_dir}/{CLAUDE_SETTINGS_REL}"
    fragment_path = f"{run_dir}/{SEEDED_FRAGMENT_REL}"
    lab_env_path = f"{run_dir}/{LAB_ENV_REL}"
    plugin_path = f"{run_dir}/{PLUGIN_REL}"
    links = " && ".join(
        f'[ -e "{home}" ] || ln -s {target} "{home}"' for home, target in CREDENTIAL_LINKS
    )
    # Persisting the CLI-native session id (--session-id / -s) onto the todo is
    # T1's job; the trailing echo gives the model one stable RUN id to reference.
    return (
        f'mkdir -p "{run_dir}/.claude" "{run_dir}/.gaia" "{run_dir}/.opencode/plugins" '
        "/workspace/.credentials/claude /workspace/.credentials/codex "
        "/workspace/.credentials/opencode $HOME/.local/share"
        f" && {links}"
        f" && {LOCAL_BIN_EXPORT}"
        f" && {CLAUDE_INSTALL_LINE}"
        f" && {OPENCODE_INSTALL_LINE}"
        f" && echo '{fragment_b64}' | base64 -d > \"{fragment_path}\""
        f" && echo '{merge_b64}' | base64 -d > {MERGE_SCRIPT_PATH}"
        f' && python3 {MERGE_SCRIPT_PATH} "{fragment_path}" "{settings_path}"'
        f" && echo '{plugin_b64}' | base64 -d > \"{plugin_path}\""
        f' && echo \'{env_b64}\' | base64 -d > "{lab_env_path}" && chmod 600 "{lab_env_path}"'
        f' && . "{lab_env_path}" && export {LAB_CALLBACK_URL_VAR} {LAB_TOKEN_VAR} {LAB_SESSION_ID_VAR}'
        f" && echo '{LAB_RUN_ID_VAR}={session_id}'"
    )
