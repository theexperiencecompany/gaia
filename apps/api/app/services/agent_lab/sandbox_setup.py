"""Per-run sandbox seeding for Agent Lab: hooks settings, plugin, env file, credential links.

The vendored claude_hooks.json is a template whose URL and token placeholders
are rendered per run, so no host or credential is baked into the repo.
Everything lands under the run's workdir, so concurrent runs keep separate
tokens: .gaia/claude-settings.json (claude --settings), the OpenCode plugin
under .opencode/plugins (OPENCODE_CONFIG_DIR) and the sourceable .gaia/lab-env.
The CLIs run in the user's repo, so both find their hooks by path from the run
env, never from the working directory. Credential dirs are linked, never
copied, into /workspace/.credentials for JuiceFS persistence, link-if-missing
so a live login is never clobbered.
"""

import base64
from pathlib import Path
import shlex
from typing import Final

from app.config.settings import settings
from app.constants.execute import SANDBOX_LAB_EVENTS_TOKEN_TTL_SECONDS
from app.services.agent_lab.lab_runs import run_dir
from app.services.sandbox.execute_token import mint_execute_token
from app.utils.errors import AppError

URL_PLACEHOLDER: Final[str] = "{{GAIA_LAB_EVENTS_URL}}"
TOKEN_PLACEHOLDER: Final[str] = "{{GAIA_LAB_TOKEN}}"

FRAGMENT_FILENAME: Final[str] = "claude_hooks.json"
PLUGIN_FILENAME: Final[str] = "opencode_notify_plugin.js"

# Per-run layout, all relative to the run's workdir (never global paths).
CLAUDE_SETTINGS_REL: Final[str] = ".gaia/claude-settings.json"
LAB_ENV_REL: Final[str] = ".gaia/lab-env"
OPENCODE_CONFIG_REL: Final[str] = ".opencode"
PLUGIN_REL: Final[str] = f"{OPENCODE_CONFIG_REL}/plugins/gaia_lab_notify.js"

# The run env: hooks read the first two at fire time, the CLIs the last two at launch.
LAB_CALLBACK_URL_VAR: Final[str] = "GAIA_LAB_CALLBACK_URL"
LAB_TOKEN_VAR: Final[str] = "GAIA_LAB_TOKEN"
LAB_RUN_ID_VAR: Final[str] = "GAIA_LAB_RUN_ID"
LAB_CLAUDE_SETTINGS_VAR: Final[str] = "GAIA_LAB_CLAUDE_SETTINGS"
OPENCODE_CONFIG_DIR_VAR: Final[str] = "OPENCODE_CONFIG_DIR"

# Install-if-missing, one line per CLI. The drive skills
# (lab-claude-drive, lab-opencode-drive) are the source of truth for method.
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
    ("$HOME/.local/share/opencode", "/workspace/.credentials/opencode"),
)


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


def mint_lab_hooks_token(user_id: str, run_id: str) -> str:
    """Per-run hooks token; empty tool scope keeps it off /sandbox/execute."""
    return mint_execute_token(
        user_id,
        run_id,
        scoped_tool_names=[],
        ttl_seconds=SANDBOX_LAB_EVENTS_TOKEN_TTL_SECONDS,
    )


def render_hooks_fragment(events_url: str, token: str) -> str:
    """Render the vendored fragment with per-run values; fails loud on drift."""
    if not events_url or not token:
        raise AppError(
            message="lab hooks fragment has no empty fields",
            why="events_url and token are both required to render the push config",
            fix="resolve the callback URL and mint the hooks token first",
            status_code=500,
            code="agent_lab_hooks_empty_input",
        )
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


def lab_env(events_url: str, token: str, run_id: str) -> dict[str, str]:
    """Return the run env, the one source for both the command env and the lab-env file."""
    folder = run_dir(run_id)
    return {
        LAB_CALLBACK_URL_VAR: events_url,
        LAB_TOKEN_VAR: token,
        LAB_RUN_ID_VAR: run_id,
        LAB_CLAUDE_SETTINGS_VAR: f"{folder}/{CLAUDE_SETTINGS_REL}",
        OPENCODE_CONFIG_DIR_VAR: f"{folder}/{OPENCODE_CONFIG_REL}",
    }


def build_seed_command(events_url: str, token: str, run_id: str) -> str:
    """Return one idempotent shell script seeding settings + plugin + env + links into the run workdir."""
    if not run_id:
        raise AppError(
            message="lab seed needs a run id",
            why="run_id is empty, so there is no workdir and the token names no run",
            fix="mint the run id first, then seed with it",
            status_code=500,
            code="agent_lab_seed_missing_run_id",
        )
    folder = run_dir(run_id)
    env = lab_env(events_url, token, run_id)
    settings_b64 = _b64(render_hooks_fragment(events_url, token))
    plugin_b64 = _b64(Path(__file__).with_name(PLUGIN_FILENAME).read_text())
    env_b64 = _b64("".join(f"{key}={shlex.quote(value)}\n" for key, value in env.items()))
    settings_path = env[LAB_CLAUDE_SETTINGS_VAR]
    plugin_path = f"{folder}/{PLUGIN_REL}"
    lab_env_path = f"{folder}/{LAB_ENV_REL}"
    links = " && ".join(
        f'[ -e "{home}" ] || ln -s {target} "{home}"' for home, target in CREDENTIAL_LINKS
    )
    targets = " ".join(target for _, target in CREDENTIAL_LINKS)
    return (
        f'mkdir -p "{folder}/.gaia" "{folder}/{OPENCODE_CONFIG_REL}/plugins" {targets} $HOME/.local/share'
        f" && {links}"
        f" && {LOCAL_BIN_EXPORT}"
        f" && {CLAUDE_INSTALL_LINE}"
        f" && {OPENCODE_INSTALL_LINE}"
        f" && echo '{settings_b64}' | base64 -d > \"{settings_path}\""
        f" && echo '{plugin_b64}' | base64 -d > \"{plugin_path}\""
        f' && echo \'{env_b64}\' | base64 -d > "{lab_env_path}" && chmod 600 "{lab_env_path}"'
    )


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()
