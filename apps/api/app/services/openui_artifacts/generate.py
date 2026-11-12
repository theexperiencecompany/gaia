"""Write an artifact program with the artifact model over the OpenAI Responses API.

The per-kind prompt is static, so it is the request's instructions and caches by prefix
under one prompt_cache_key per kind; the brief (and, for a repair, the program and its
problems) is the input.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import time

from openai import AsyncOpenAI, BadRequestError
from openai.types.responses import (
    ResponseCompletedEvent,
    ResponseRefusalDeltaEvent,
    ResponseTextDeltaEvent,
    ResponseUsage,
)

from app.constants.llm import ARTIFACT_MODEL_NAME, ARTIFACT_REASONING_EFFORT
from app.constants.openui_artifacts import (
    ARTIFACT_MAX_OUTPUT_TOKENS,
    ARTIFACT_PROMPTS_DIR,
    ARTIFACT_REPAIR_INSTRUCTION,
)
from app.constants.providers import CredentialProviderName
from app.models.openui_artifact_models import ArtifactKind
from app.services.llm_metering import LLMCallContext, TokenUsage, record_llm_call
from app.services.providers.provider_credentials_service import resolve
from app.utils.background_tasks import spawn_background_task
from app.utils.errors import AppError

ARTIFACT_PROMPTS: dict[ArtifactKind, str] = {
    kind: (ARTIFACT_PROMPTS_DIR / f"{kind.value}.txt").read_text(encoding="utf-8")
    for kind in ArtifactKind
}

# OpenAI's code for a request its safety system refused to serve.
_REFUSED_PROMPT_CODE = "invalid_prompt"


class ArtifactModelNotConfiguredError(AppError):
    """No OpenAI credential, so the artifact model cannot run."""


class ArtifactRefusedError(AppError):
    """The provider refused the request; the caller logs it in full and fails the tool."""


@dataclass(frozen=True)
class GeneratedReply:
    """One model reply and what it cost."""

    text: str
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    #: Milliseconds from the request to the first complete statement after root; None when
    #: the reply never got that far.
    first_component_ms: float | None


@dataclass(frozen=True)
class ArtifactRequest:
    kind: ArtifactKind
    brief: str
    user_id: str
    conversation_id: str | None


DeltaSink = Callable[[str], Awaitable[None]]


def _input_for(brief: str) -> str:
    return f"Today is {datetime.now(UTC).strftime('%d %B %Y')}.\n\n{brief}"


def repair_input(brief: str, program: str, problems: list[str]) -> str:
    listed = "\n- ".join(problems)
    return (
        f"{brief}\n\nYour program:\n{program}\n\nProblems:\n- {listed}\n"
        f"{ARTIFACT_REPAIR_INSTRUCTION}."
    )


async def _client() -> AsyncOpenAI:
    config = await resolve(CredentialProviderName.OPENAI)
    if config is None or not config.api_key:
        raise ArtifactModelNotConfiguredError(
            message="artifacts need an OpenAI key",
            fix="set OPENAI_API_KEY or add an OpenAI credential in Settings > Providers",
        )
    return AsyncOpenAI(api_key=config.api_key)


def _meter(request: ArtifactRequest, usage: ResponseUsage | None, duration_ms: float) -> None:
    if usage is None:
        return
    cached = usage.input_tokens_details.cached_tokens if usage.input_tokens_details else 0
    reasoning = usage.output_tokens_details.reasoning_tokens if usage.output_tokens_details else 0
    spawn_background_task(
        record_llm_call(
            user_id=request.user_id,
            model_name=ARTIFACT_MODEL_NAME,
            usage=TokenUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cached_tokens=cached,
                reasoning_tokens=reasoning,
            ),
            context=LLMCallContext(
                agent_name="create_artifact",
                background=False,
                charge_to_budget=True,
                conversation_id=request.conversation_id,
                duration_ms=duration_ms,
            ),
        ),
        name="artifact_meter_call",
    )


def _refused(exc: BadRequestError) -> bool:
    return exc.code == _REFUSED_PROMPT_CODE


async def generate_reply(
    request: ArtifactRequest, model_input: str, on_delta: DeltaSink | None = None
) -> GeneratedReply:
    """Stream one reply, handing each text delta to on_delta as it arrives."""
    client = await _client()
    started = time.perf_counter()
    text: list[str] = []
    newlines = 0
    first_component_ms: float | None = None
    usage: ResponseUsage | None = None
    try:
        stream = await client.responses.create(
            model=ARTIFACT_MODEL_NAME,
            instructions=ARTIFACT_PROMPTS[request.kind],
            input=model_input,
            reasoning={"effort": ARTIFACT_REASONING_EFFORT},
            max_output_tokens=ARTIFACT_MAX_OUTPUT_TOKENS,
            prompt_cache_key=f"artifact-openui-{request.kind.value}",
            stream=True,
        )
        async for event in stream:
            if isinstance(event, ResponseTextDeltaEvent):
                text.append(event.delta)
                newlines += event.delta.count("\n")
                # root's line and the first statement after it are both complete
                if first_component_ms is None and newlines >= 2:
                    first_component_ms = (time.perf_counter() - started) * 1000
                if on_delta is not None:
                    await on_delta(event.delta)
            elif isinstance(event, ResponseRefusalDeltaEvent):
                raise ArtifactRefusedError(message="the artifact model refused the request")
            elif isinstance(event, ResponseCompletedEvent):
                usage = event.response.usage
    except BadRequestError as exc:
        if _refused(exc):
            raise ArtifactRefusedError(message="the provider refused the artifact request") from exc
        raise
    finally:
        _meter(request, usage, (time.perf_counter() - started) * 1000)
    return GeneratedReply(
        text="".join(text),
        input_tokens=usage.input_tokens if usage else 0,
        cached_tokens=(
            usage.input_tokens_details.cached_tokens if usage and usage.input_tokens_details else 0
        ),
        output_tokens=usage.output_tokens if usage else 0,
        first_component_ms=first_component_ms,
    )


async def write_program(request: ArtifactRequest, on_delta: DeltaSink) -> GeneratedReply:
    return await generate_reply(request, _input_for(request.brief), on_delta)


async def repair_program(
    request: ArtifactRequest, program: str, problems: list[str]
) -> GeneratedReply:
    return await generate_reply(request, repair_input(_input_for(request.brief), program, problems))
