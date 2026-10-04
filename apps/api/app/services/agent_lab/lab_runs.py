"""Per-run identity for agent-lab runs: workdir layout plus todo reference routing.

Previously part of the deleted agent-lab tool module. The keep-warm worker
still resolves runs through these shapes, so they live here — not behind
any tool.
"""

from typing import Final

#: Routing entry in a todo's references: ``lab:<run_id>:<cli_session_id>``.
LAB_REF_PREFIX: Final[str] = "lab:"

#: Parent dir for per-run workdirs; one run owns exactly one subdir.
LAB_RUN_DIR_PREFIX: Final[str] = "/workspace/.gaia/lab"

#: Seed runs CLI installs, so allow time for a cold download.
LAB_SEED_TIMEOUT_SECONDS: Final[int] = 300


def run_dir(run_id: str) -> str:
    """Return the run's workdir under the shared parent."""
    return f"{LAB_RUN_DIR_PREFIX}/{run_id}"


def routing_ref(run_id: str, cli_session_id: str) -> str:
    """Return the todo references entry routing messages to this run."""
    return f"{LAB_REF_PREFIX}{run_id}:{cli_session_id}"


def parse_lab_routing_ref(entry: str) -> tuple[str, str] | None:
    """Split a ``lab:<run_id>:<cli_session_id>`` entry; None for anything else."""
    if not entry.startswith(LAB_REF_PREFIX):
        return None
    _, _, rest = entry.partition(":")
    run_id, sep, cli_session_id = rest.partition(":")
    if not sep or not run_id or not cli_session_id:
        return None
    return run_id, cli_session_id
