"""Ask the real executor, on the real model, to connect tools GAIA does not ship, and score each draft.

Run against a stack booted with `mise infisical -- dev --agent`:
mise connectors:benchmark [tool ...]. For each tool a fresh Pro user sends "Connect <tool> using
its official <CLI|REST API|SDK>" as a chat message, so comms and the executor run exactly as for
a user. define_connector always asks the user first, so the draft is read from that pending
approval. It is then held to real calls on both runners: the spec parsed,
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
from uuid import uuid4

import httpx

from app.constants.connectors import DEFINE_CONNECTOR_TOOL, MANAGED_BY_CONNECTOR
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.integrations import integration_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.models.connector_models import ConnectorSpec
from app.models.conversation_log_models import EntryKind
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

_HTTP_TIMEOUT_SECONDS = 60
# A drafting turn: retrieval, docs, maybe a release checksum fetch, then define_connector.
_TURN_TIMEOUT_SECONDS = 600
_POLL_SECONDS = 5
_PARALLEL_TOOLS = 5


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


async def _turn_settled(client: httpx.AsyncClient, api: str, user: "DevUser") -> None:
    url = f"{api}/api/v1/conversations/{user.conversation_id}/events"
    async with client.stream("GET", url, params={"after": 0}, headers=user.headers) as events:
        async for line in events.aiter_lines():
            if EntryKind.REPLY_SETTLED in line:
                return


async def _ask_in_chat(
    client: httpx.AsyncClient, api: str, user: "DevUser", tool: Tool
) -> ConnectorSpec | None:
    """Send "connect <tool>" as a chat message; return the draft once it exists, or None when the turn ends without one."""
    since = datetime.now(UTC)
    text = f"Connect {tool.name} using its official {tool.preset.value}. I'll paste the key into the card."
    sent = await client.post(
        f"{api}/api/v1/conversations/{user.conversation_id}/messages",
        headers=user.headers,
        json={"message_id": str(uuid4()), "text": text},
    )
    sent.raise_for_status()
    settled = asyncio.create_task(_turn_settled(client, api, user))
    try:
        async with asyncio.timeout(_TURN_TIMEOUT_SECONDS):
            while True:
                if (spec := await _drafted_spec(user.user_id, since)) is not None:
                    return spec
                if settled.done():
                    return await _drafted_spec(user.user_id, since)
                await asyncio.sleep(_POLL_SECONDS)
    except TimeoutError:
        return None
    finally:
        settled.cancel()


async def _drafted_spec(user_id: str, since: datetime) -> ConnectorSpec | None:
    """The spec the agent drafted: waiting on the user's approval (define_connector always asks), or saved."""
    pending = [
        p
        for p in await approval_ledger_repository.list_pending_for_user(user_id)
        if p.tool_name == DEFINE_CONNECTOR_TOOL and "spec" in p.args
    ]
    if pending:
        return ConnectorSpec.model_validate(pending[-1].args["spec"])
    records = await user_integration_repository.list_for_user(user_id)
    docs = await integration_repository.find_custom_by_ids([r.integration_id for r in records])
    saved = [
        doc.connector_config
        for doc in docs
        if doc.managed_by == MANAGED_BY_CONNECTOR
        and doc.connector_config is not None
        and (doc.updated_at or doc.created_at).replace(tzinfo=UTC) >= since
    ]
    return saved[-1] if saved else None


@dataclass(frozen=True)
class DevUser:
    email: str
    user_id: str
    conversation_id: str

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Dev-User": self.email}


async def score_tool(client: httpx.AsyncClient, api: str, user: DevUser, tool: Tool) -> Score:
    """Ask for the connector, then hold the spec it drafted to real calls on both runners."""
    spec = await _ask_in_chat(client, api, user, tool)
    if spec is None:
        why = "the turn ended without a define_connector call"
        return Score(tool, {"spec": StageResult(Stage.SPEC, Outcome.FAIL, why)})
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


async def _fresh_pro_user(client: httpx.AsyncClient, api: str, tool: Tool) -> DevUser:
    """Mint one Pro dev user per tool with a real conversation, where its approvals are filed."""
    slug = "".join(ch for ch in tool.name.lower() if ch.isalnum())
    email = f"delivered+bench-{slug}@resend.dev"
    minted = await client.post(f"{api}/api/v1/dev/users", json={"email": email, "name": tool.name})
    minted.raise_for_status()
    seeded = await client.post(f"{api}/api/v1/dev/seed", json={"email": email, "pro": True})
    seeded.raise_for_status()
    conversation_id = str(uuid4())
    return DevUser(email, str(minted.json()["id"]), conversation_id)


async def _main(only: list[str], api: str) -> int:
    tools = [t for t in TOOLS if not only or t.name.lower() in {o.lower() for o in only}]
    gate = asyncio.Semaphore(_PARALLEL_TOOLS)
    async with httpx.AsyncClient(timeout=httpx.Timeout(_HTTP_TIMEOUT_SECONDS, read=None)) as client:

        async def one(tool: Tool) -> Score:
            async with gate:
                user = await _fresh_pro_user(client, api, tool)
                score = await score_tool(client, api, user, tool)
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
