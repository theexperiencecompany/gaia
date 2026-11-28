"""Ask the real executor, on the real model, to connect tools GAIA does not ship, and score each draft.

Run against a stack booted with `mise infisical -- dev --agent`:
mise connectors:benchmark [tool ...]. For each tool the executor gets "Connect <tool> using its
official <CLI|REST API|SDK>" through POST /api/v1/dev/executor, exactly the preparation comms
hands it. The connector it saved is then held to real calls on both runners: the spec parsed,
the pinned install ran (and, for a CLI, its help printed), a bad key was refused as an auth
failure, and, only where the team holds a key, the verify call proved it and named the account.
Prints one row per tool and the pass rate per stage. Not a CI lane; the results are not committed.
"""

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import os

import httpx

from app.constants.connectors import MANAGED_BY_CONNECTOR
from app.db.repositories.integrations import integration_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.models.connector_models import ConnectorSpec
from app.services.connectors.docker_runner import DockerConnectorRunner
from app.services.connectors.e2b_runner import E2BConnectorRunner
from scripts.connectors.stages import (
    Outcome,
    Stage,
    StageResult,
    Target,
    bad_key_stage,
    install_stage,
    verify_stage,
)

_EXECUTOR_TIMEOUT_SECONDS = 900
_PARALLEL_TOOLS = 3


class Preset(StrEnum):
    CLI = "CLI"
    REST = "REST API"
    SDK = "Python SDK"


@dataclass(frozen=True)
class Tool:
    name: str
    preset: Preset
    # Env var holding a real team key; the verify stage runs only when it is set.
    key_env: str | None = None


# None of these is in the connector catalog or the platform integrations.
TOOLS: tuple[Tool, ...] = (
    Tool("Terraform Cloud", Preset.CLI),
    Tool("Pulumi", Preset.CLI),
    Tool("ngrok", Preset.CLI),
    Tool("GitLab", Preset.CLI),
    Tool("CircleCI", Preset.CLI),
    Tool("Snyk", Preset.CLI),
    Tool("Firebase", Preset.CLI),
    Tool("Neon", Preset.CLI),
    Tool("Turso", Preset.CLI),
    Tool("Hugging Face", Preset.CLI, "HUGGINGFACE_API_KEY"),
    Tool("Mailgun", Preset.REST),
    Tool("Algolia", Preset.REST),
    Tool("Pinecone", Preset.REST),
    Tool("Mistral AI", Preset.REST),
    Tool("Groq", Preset.REST),
    Tool("PagerDuty", Preset.REST),
    Tool("Datadog", Preset.REST),
    Tool("Vultr", Preset.REST),
    Tool("Linode", Preset.REST),
    Tool("ElevenLabs", Preset.REST, "ELEVENLABS_API_KEY"),
    Tool("OpenRouter", Preset.REST, "OPENROUTER_API_KEY"),
    Tool("Tavily", Preset.REST, "TAVILY_API_KEY"),
    Tool("Firecrawl", Preset.REST, "FIRECRAWL_API_KEY"),
    Tool("Langfuse Cloud", Preset.REST, "LANGFUSE_BASIC_KEY"),
    Tool("Anthropic", Preset.SDK),
    Tool("Cohere", Preset.SDK),
    Tool("AssemblyAI", Preset.SDK, "ASSEMBLYAI_API_KEY"),
    Tool("Deepgram", Preset.SDK, "DEEPGRAM_API_KEY"),
    Tool("Google Gemini", Preset.SDK, "GOOGLE_API_KEY"),
    Tool("Replicate", Preset.SDK),
)

_COLUMNS = ("spec", "install e2b", "install docker", "bad key e2b", "bad key docker", "verify")
_NOT_RUN = StageResult(Stage.SPEC, Outcome.SKIP, "no spec")


@dataclass(frozen=True)
class Score:
    tool: Tool
    cells: dict[str, StageResult]


def _team_key(tool: Tool) -> str | None:
    if tool.key_env == "LANGFUSE_BASIC_KEY":
        public, secret = (
            os.environ.get("LANGFUSE_PUBLIC_KEY"),
            os.environ.get("LANGFUSE_SECRET_KEY"),
        )
        return f"{public}:{secret}" if public and secret else None
    return os.environ.get(tool.key_env) if tool.key_env else None


async def _ask_executor(client: httpx.AsyncClient, api: str, email: str, tool: Tool) -> str:
    task = (
        f"Connect {tool.name} using its official {tool.preset.value}, so I can use it from GAIA. "
        "I will paste the key into the card."
    )
    response = await client.post(f"{api}/api/v1/dev/executor", json={"email": email, "task": task})
    if response.is_error:
        # The run itself failed (a gateway timeout on a long run): that is this tool's score.
        return f"executor answered HTTP {response.status_code}"
    return str(response.json().get("message", ""))


async def _drafted_spec(user_id: str, since: datetime) -> list[tuple[str, ConnectorSpec]]:
    records = await user_integration_repository.list_for_user(user_id)
    docs = await integration_repository.find_custom_by_ids([r.integration_id for r in records])
    return [
        (doc.name, doc.connector_config)
        for doc in docs
        if doc.managed_by == MANAGED_BY_CONNECTOR
        and doc.connector_config is not None
        and (doc.updated_at or doc.created_at).replace(tzinfo=UTC) >= since
    ]


async def score_tool(
    client: httpx.AsyncClient, api: str, email: str, user_id: str, tool: Tool
) -> Score:
    """Ask for the connector, then hold whatever it saved to real calls on both runners."""
    since = datetime.now(UTC)
    reply = await _ask_executor(client, api, email, tool)
    drafted = await _drafted_spec(user_id, since)
    if not drafted:
        said = " ".join(reply.split())[:140]
        return Score(tool, {"spec": StageResult(Stage.SPEC, Outcome.FAIL, f"none saved: {said}")})
    _, spec = drafted[-1]
    cells = {"spec": StageResult(Stage.SPEC, Outcome.PASS, f"{spec.kind} {spec.provider_domain}")}
    e2b, docker = E2BConnectorRunner(), DockerConnectorRunner()
    cells["install e2b"], cells["install docker"] = await asyncio.gather(
        install_stage(spec, e2b), install_stage(spec, docker)
    )
    cells["bad key e2b"], cells["bad key docker"] = await asyncio.gather(
        bad_key_stage(spec, e2b), bad_key_stage(spec, docker)
    )
    key = _team_key(tool)
    cells["verify"] = (
        await verify_stage(spec, Target(e2b, key))
        if key
        else StageResult(Stage.VERIFY, Outcome.SKIP, "no credential")
    )
    return Score(tool, cells)


def _print(scores: list[Score]) -> None:
    width = max(len(score.tool.name) for score in scores)
    print(f"\n{'tool':<{width}}  {'preset':<10}  " + "  ".join(f"{c:<14}" for c in _COLUMNS))
    for score in scores:
        cells = [score.cells.get(c, _NOT_RUN).outcome.value for c in _COLUMNS]
        print(
            f"{score.tool.name:<{width}}  {score.tool.preset.value:<10}  "
            + "  ".join(f"{c:<14}" for c in cells)
        )
    print("\nPass rate per stage (passed / attempted, skips excluded):")
    for column in _COLUMNS:
        results = [s.cells[column] for s in scores if column in s.cells]
        attempted = [r for r in results if r.outcome is not Outcome.SKIP]
        passed = sum(r.outcome is Outcome.PASS for r in attempted)
        print(f"  {column:<14} {passed}/{len(attempted)}")
    whole = sum(
        all(s.cells.get(c, _NOT_RUN).outcome is not Outcome.FAIL for c in _COLUMNS)
        and "install e2b" in s.cells
        for s in scores
    )
    print(f"  every attempted stage passed: {whole}/{len(scores)}")
    print("\nFailures:")
    for score in scores:
        for column in _COLUMNS:
            result = score.cells.get(column)
            if result is not None and result.outcome is Outcome.FAIL:
                print(f"  {score.tool.name} {column}: {result.detail}")


async def _fresh_pro_user(client: httpx.AsyncClient, api: str, tool: Tool) -> tuple[str, str]:
    """Mint one Pro dev user per tool, so no draft is scored against another tool's connector."""
    slug = "".join(ch for ch in tool.name.lower() if ch.isalnum())
    email = f"delivered+bench-{slug}@resend.dev"
    minted = await client.post(f"{api}/api/v1/dev/users", json={"email": email, "name": tool.name})
    minted.raise_for_status()
    seeded = await client.post(f"{api}/api/v1/dev/seed", json={"email": email, "pro": True})
    seeded.raise_for_status()
    return email, str(minted.json()["id"])


async def _main(only: list[str], api: str) -> int:
    tools = [t for t in TOOLS if not only or t.name.lower() in {o.lower() for o in only}]
    gate = asyncio.Semaphore(_PARALLEL_TOOLS)
    async with httpx.AsyncClient(timeout=_EXECUTOR_TIMEOUT_SECONDS) as client:

        async def one(tool: Tool) -> Score:
            async with gate:
                email, user_id = await _fresh_pro_user(client, api, tool)
                score = await score_tool(client, api, email, user_id, tool)
                print(f"scored {tool.name}", flush=True)
                return score

        scores = list(await asyncio.gather(*(one(tool) for tool in tools)))
    _print(scores)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tools", nargs="*", help="tool names to run (default: all thirty)")
    parser.add_argument("--api", default=f"http://localhost:{os.environ.get('API_PORT', '8000')}")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args.tools, args.api)))
