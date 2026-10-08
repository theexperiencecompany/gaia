"""Per-run sandbox seeding for agent runs: the agents' home plus the run's env file.

Hooks, the OpenCode plugin and the save/hook scripts live once per sandbox
under ~/agents (agents_home.py) and read the run's identity from the process
env, so a run only adds runs/<run_id>/lab-env: the sourceable copy of that env
for a later bash call (a resume) that gets no env injected.
"""

import shlex
from typing import Final

from app.config.settings import settings
from app.constants.execute import SANDBOX_LAB_EVENTS_TOKEN_TTL_SECONDS
from app.services.agent_lab.agents_home import (
    CLAUDE_SETTINGS_PATH,
    OPENCODE_CONFIG_DIR,
    build_agents_setup_command,
    write_file_step,
)
from app.services.agent_lab.lab_runs import run_dir
from app.services.sandbox.execute_token import mint_execute_token
from app.utils.errors import AppError

LAB_ENV_FILENAME: Final[str] = "lab-env"

# The run env: gaia-hook reads the first two at fire time, the CLIs the last two at launch.
LAB_CALLBACK_URL_VAR: Final[str] = "GAIA_LAB_CALLBACK_URL"
LAB_TOKEN_VAR: Final[str] = "GAIA_LAB_TOKEN"
LAB_RUN_ID_VAR: Final[str] = "GAIA_LAB_RUN_ID"
LAB_CLAUDE_SETTINGS_VAR: Final[str] = "GAIA_LAB_CLAUDE_SETTINGS"
OPENCODE_CONFIG_DIR_VAR: Final[str] = "OPENCODE_CONFIG_DIR"


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


def lab_env(events_url: str, token: str, run_id: str) -> dict[str, str]:
    """Return the run env, the one source for both the command env and the lab-env file."""
    return {
        LAB_CALLBACK_URL_VAR: events_url,
        LAB_TOKEN_VAR: token,
        LAB_RUN_ID_VAR: run_id,
        LAB_CLAUDE_SETTINGS_VAR: CLAUDE_SETTINGS_PATH,
        OPENCODE_CONFIG_DIR_VAR: OPENCODE_CONFIG_DIR,
    }


def lab_env_path(run_id: str) -> str:
    """Return where the run's sourceable env file lives."""
    return f"{run_dir(run_id)}/{LAB_ENV_FILENAME}"


def build_seed_command(events_url: str, token: str, run_id: str) -> str:
    """Return one idempotent shell script: the agents' home setup, then the run's private env file."""
    if not run_id:
        raise AppError(
            message="lab seed needs a run id",
            why="run_id is empty, so there is no run folder and the token names no run",
            fix="mint the run id first, then seed with it",
            status_code=500,
            code="agent_lab_seed_missing_run_id",
        )
    folder = shlex.quote(run_dir(run_id))
    env_file = "".join(
        f"{key}={shlex.quote(value)}\n" for key, value in lab_env(events_url, token, run_id).items()
    )
    return " && ".join(
        (
            build_agents_setup_command(),
            f"mkdir -p {folder}",
            f"chmod 700 {folder}",
            write_file_step(lab_env_path(run_id), env_file),
            f"chmod 600 {shlex.quote(lab_env_path(run_id))}",
        )
    )
