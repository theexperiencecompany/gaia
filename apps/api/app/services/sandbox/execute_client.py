"""Code mode's sandbox side: the stdlib gaia client and per-invocation env.

Bash-driven scripting has no approval gate by design, so the token's security
is layered instead of gated:

- **Per-invocation mint, per-process delivery.** Every bash command gets its
  own token via ``commands.run(envs=...)`` — envd sets env on that process
  only, and the hardened template (non-dumpable daemons, hidepid /proc) keeps
  other processes from reading it. Nothing is written to disk or the sandbox's
  global env.
- **TTL bound to the command's own timeout** (plus a small buffer), so a
  leaked token is dead within minutes.
- **Server-side blast radius** — per-token call budget + per-minute rate limit
  and an audit entry per call, enforced on the callback route.
- **Kill switch** — unsetting SANDBOX_EXECUTE_TOKEN_SECRET invalidates every
  outstanding token instantly.

The residual, accepted risk: for the token's lifetime, code running in the
user's sandbox can call the user's tools without a per-action approval.
"""

from langchain_core.runnables import RunnableConfig

from app.config.settings import settings
from app.constants.execute import (
    SANDBOX_CLIENT_DIR,
    SANDBOX_EXECUTE_CLIENT_TIMEOUT_BUFFER_SECONDS,
    SANDBOX_EXECUTE_TOKEN_TTL_BUFFER_SECONDS,
    SANDBOX_SCHEMA_CACHE_TTL_SECONDS,
    SANDBOX_TOOL_DOCS_DIR,
)
from app.constants.llm import TOOL_EXECUTION_TIMEOUT_SECONDS
from app.models.agent_models import agent_configurable
from app.services.sandbox.execute_token import mint_execute_token

# Stdlib-only client seeded into the sandbox per bash invocation (idempotent
# write, no template rebuild, no network install). The __TOKEN__ placeholders
# keep the host-side constants the single source of truth.
_CLIENT_TEMPLATE = '''\
"""GAIA sandbox tool client. Usage: from gaia import execute, schema"""
import json
import os
import time
import urllib.request

_TOOL_DOCS_DIR = "__TOOL_DOCS_DIR__"
_SCHEMA_CACHE_TTL_SECONDS = __SCHEMA_CACHE_TTL_SECONDS__
# Above the host's own bound, so the host is always the one that gives up and
# says whether the call landed. Giving up first would abandon a mutation still
# in flight, and the retry the docs prescribe would then duplicate it.
_REQUEST_TIMEOUT_SECONDS = __REQUEST_TIMEOUT_SECONDS__


class GaiaToolError(RuntimeError):
    """A tool call the host refused or failed to validate; str() carries the detail."""


def _post(url_env: str, payload: dict) -> dict:
    request = urllib.request.Request(
        os.environ[url_env],
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + os.environ["GAIA_EXECUTE_TOKEN"],
        },
    )
    with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode())


def execute(tool_name: str, data: dict | None = None):
    """Run a GAIA tool. Returns the parsed JSON result or raises GaiaToolError."""
    body = _post("GAIA_EXECUTE_URL", {"tool_name": tool_name, "data": data or {}})
    if not body.get("ok"):
        raise GaiaToolError(json.dumps(body.get("error"), indent=2))
    return body["output"]


def schema(tool_name: str) -> dict:
    """The full tool contract (input schema, output schemas, description).

    Cached as one file per tool under the tool-docs folder; reading that file
    directly is equivalent.
    """
    cache_path = os.path.join(_TOOL_DOCS_DIR, tool_name + ".json")
    try:
        if time.time() - os.path.getmtime(cache_path) < _SCHEMA_CACHE_TTL_SECONDS:
            with open(cache_path) as cached:
                return json.load(cached)
    except (OSError, ValueError):
        pass
    body = _post("GAIA_SCHEMA_URL", {"tool_name": tool_name})
    os.makedirs(_TOOL_DOCS_DIR, exist_ok=True)
    with open(cache_path, "w") as out:
        json.dump(body, out, indent=2)
    return body
'''


def render_sandbox_client_source(*, tool_docs_dir: str, schema_cache_ttl_seconds: int) -> str:
    """The client source with its host-side constants substituted in.

    The ONE place the placeholders are filled. A second copy of this list (the
    test's, which built its own source to point the cache at a tmp dir) went
    stale the moment a placeholder was added, and the client it exercised was
    no longer the one shipped.
    """
    return (
        _CLIENT_TEMPLATE.replace("__TOOL_DOCS_DIR__", tool_docs_dir)
        .replace("__SCHEMA_CACHE_TTL_SECONDS__", str(schema_cache_ttl_seconds))
        .replace(
            "__REQUEST_TIMEOUT_SECONDS__",
            str(TOOL_EXECUTION_TIMEOUT_SECONDS + SANDBOX_EXECUTE_CLIENT_TIMEOUT_BUFFER_SECONDS),
        )
    )


GAIA_SANDBOX_CLIENT_SOURCE = render_sandbox_client_source(
    tool_docs_dir=SANDBOX_TOOL_DOCS_DIR,
    schema_cache_ttl_seconds=SANDBOX_SCHEMA_CACHE_TTL_SECONDS,
)


def sandbox_execute_enabled() -> bool:
    return bool(settings.SANDBOX_EXECUTE_TOKEN_SECRET and settings.SANDBOX_EXECUTE_CALLBACK_URL)


async def seed_execute_client(sbx: object) -> None:
    """Write the gaia client into the sandbox (idempotent, one round-trip)."""
    await sbx.files.write(f"{SANDBOX_CLIENT_DIR}/gaia.py", GAIA_SANDBOX_CLIENT_SOURCE)  # type: ignore[attr-defined]  # e2b SDK ships no stubs


def mint_execute_env(
    *,
    user_id: str,
    run_id: str,
    config: RunnableConfig,
    sandbox_id: str | None,
    command_timeout_seconds: int,
    scoped_tool_names: list[str] | None,
) -> dict[str, str]:
    """The env one bash command runs with so its scripts can call GAIA tools.

    ``run_id`` is the bash run's own id — the route's budget and audit trail
    correlate to the exact command that made the calls.

    ``scoped_tool_names`` is the calling agent's tool space (``None`` for the
    executor, whose space is the registry). It rides in the token because the
    route is the only other place a proxied tool runs, and a subagent's
    confinement has to hold there too.
    """
    token = mint_execute_token(
        user_id,
        run_id,
        stream_id=agent_configurable(config).get("stream_id"),
        sandbox_id=sandbox_id,
        scoped_tool_names=scoped_tool_names,
        ttl_seconds=command_timeout_seconds + SANDBOX_EXECUTE_TOKEN_TTL_BUFFER_SECONDS,
    )
    execute_url = str(settings.SANDBOX_EXECUTE_CALLBACK_URL)
    # PYTHONPATH makes `from gaia import execute` work from any cwd. Fresh env
    # per exec: the sandbox sets no PYTHONPATH of its own to merge with.
    return {
        "GAIA_EXECUTE_URL": execute_url,
        # The schema route is the execute route's sibling (routes.py mounts both
        # under /sandbox), so one configured callback URL covers both.
        "GAIA_SCHEMA_URL": execute_url.rsplit("/", 1)[0] + "/tool-schema",
        "GAIA_EXECUTE_TOKEN": token,
        "PYTHONPATH": SANDBOX_CLIENT_DIR,
    }
