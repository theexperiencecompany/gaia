"""The web app's own .env decides its config, not apps/web/mise.toml.

mise exports a config's [env] into every process its shims (node, pnpm) start
under apps/web, overriding the caller's environment, and Next's dotenv loader
never overrides a variable the process already has. A key in both files makes
apps/web/.env and any exported value dead config in every checkout and worktree.
"""

from __future__ import annotations

from pathlib import Path
import tomllib

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


def dotenv_keys(path: Path) -> set[str]:
    lines = (line.strip() for line in path.read_text().splitlines())
    return {line.split("=", 1)[0] for line in lines if "=" in line and not line.startswith("#")}


def test_web_mise_env_never_shadows_a_dotenv_key() -> None:
    mise_env = tomllib.loads((WEB / "mise.toml").read_text()).get("env", {})
    assert sorted(mise_env.keys() & dotenv_keys(WEB / ".env.example")) == []
