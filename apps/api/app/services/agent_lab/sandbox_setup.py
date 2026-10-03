"""Per-session sandbox seeding for Agent Lab: hooks fragment + credential links.

The vendored ``claude_hooks.json`` is a template, not a live config. Its two
placeholders are rendered per session at lab start — never hardcoded, so no
host or credential is baked into the repo or the template:

- ``{{GAIA_LAB_EVENTS_URL}}`` → ``SANDBOX_LAB_EVENTS_CALLBACK_URL`` (the
  /api/v1/lab/events URL reachable FROM the E2B sandbox, public API base).
- ``{{GAIA_LAB_TOKEN}}`` → a per-session HMAC token minted by
  :func:`mint_lab_hooks_token` (same scheme as /sandbox/execute, but with an
  EMPTY tool scope, so the token is useless on /sandbox/execute and only the
  events receiver accepts it).

The rendered fragment is written to ``/workspace/.gaia/claude-hooks.json``
(auditable) and merged into ``/workspace/.claude/settings.json`` (project
scope, so Claude Code picks it up with no extra flags). Everything lives
under ``/workspace`` so JuiceFS persists it across pause/resume and recreate.
Credential DIRS are linked (never copied) into ``/workspace/.credentials/*``
for the same reason; linking is link-if-missing only, so a live login is
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

WORKSPACE_CLAUDE_SETTINGS: Final[str] = "/workspace/.claude/settings.json"
SEEDED_FRAGMENT_PATH: Final[str] = "/workspace/.gaia/claude-hooks.json"
MERGE_SCRIPT_PATH: Final[str] = "/tmp/gaia-merge-hooks.py"

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
    """Per-session hooks token; empty tool scope keeps it off /sandbox/execute."""
    return mint_execute_token(
        user_id,
        session_id,
        scoped_tool_names=[],
        ttl_seconds=SANDBOX_LAB_EVENTS_TOKEN_TTL_SECONDS,
    )


def render_hooks_fragment(events_url: str, token: str) -> str:
    """Render the vendored fragment with per-session values; fails loud on drift."""
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


def build_seed_command(events_url: str, token: str) -> str:
    """One idempotent shell script seeding hooks + credential links into the sandbox."""
    fragment = render_hooks_fragment(events_url, token)
    fragment_b64 = base64.b64encode(fragment.encode()).decode()
    merge_b64 = base64.b64encode(MERGE_SETTINGS_SCRIPT.encode()).decode()
    links = " && ".join(
        f'[ -e "{home}" ] || ln -s {target} "{home}"' for home, target in CREDENTIAL_LINKS
    )
    return (
        "mkdir -p /workspace/.claude /workspace/.gaia "
        "/workspace/.credentials/claude /workspace/.credentials/codex "
        "/workspace/.credentials/opencode $HOME/.local/share"
        f" && {links}"
        f" && echo '{fragment_b64}' | base64 -d > {SEEDED_FRAGMENT_PATH}"
        f" && echo '{merge_b64}' | base64 -d > {MERGE_SCRIPT_PATH}"
        f" && python3 {MERGE_SCRIPT_PATH} {SEEDED_FRAGMENT_PATH} {WORKSPACE_CLAUDE_SETTINGS}"
    )
