"""create_artifact's pipeline: write the program, validate it, repair it once, store it.

A program that still fails after one repair, a provider refusal and a timeout all fail loud:
nothing is stored and the caller gets ArtifactCreationError with the reason.
"""

import asyncio
from dataclasses import dataclass, field
import hashlib
import time

from app.constants.llm import ARTIFACT_MODEL_NAME
from app.constants.openui_artifacts import (
    ARTIFACT_GENERATION_TIMEOUT_SECONDS,
    ARTIFACT_MAX_REPAIRS,
)
from app.db.repositories.openui_artifacts import openui_artifact_repository
from app.models.openui_artifact_models import ArtifactFailureReason, OpenUIArtifact
from app.services.analytics_service import capture
from app.services.openui_artifacts.generate import (
    ArtifactRefusedError,
    ArtifactRequest,
    DeltaSink,
    repair_program,
    write_program,
)
from app.services.openui_artifacts.validate import ArtifactValidation, validate_program
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.artifacts import ArtifactCreated, ArtifactFailed
from shared.py.wide_events import log


@dataclass
class ArtifactCreationError(AppError):
    """The artifact could not be made; reason and problems say why."""

    reason: ArtifactFailureReason = ArtifactFailureReason.VALIDATION
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Validated:
    validation: ArtifactValidation
    repairs: int
    output_tokens: int
    first_component_ms: float | None


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _fail(
    request: ArtifactRequest, reason: ArtifactFailureReason, problems: list[str]
) -> ArtifactCreationError:
    capture(
        UserId(request.user_id),
        ArtifactFailed(kind=request.kind.value, reason=reason.value, problem_count=len(problems)),
    )
    log.set_ns("artifact", status="failed", reason=reason.value, problems=problems[:20])
    return ArtifactCreationError(
        message=f"the artifact could not be made ({reason.value})",
        meta={"problems": problems[:20]},
        reason=reason,
        problems=problems,
    )


async def _validated(request: ArtifactRequest, on_delta: DeltaSink) -> _Validated:
    """Write the program, then repair it once if validation finds problems."""
    first = await write_program(request, on_delta)
    validation = await validate_program(first.text, request.brief)
    output_tokens = first.output_tokens
    repairs = 0
    while not validation.ok and repairs < ARTIFACT_MAX_REPAIRS:
        repairs += 1
        log.set_ns("artifact", first_problems=validation.problems[:20])
        repaired = await repair_program(request, validation.program, validation.problems)
        output_tokens += repaired.output_tokens
        validation = await validate_program(repaired.text, request.brief)
    return _Validated(validation, repairs, output_tokens, first.first_component_ms)


async def create_openui_artifact(
    request: ArtifactRequest, title: str, on_delta: DeltaSink
) -> OpenUIArtifact:
    """Write, validate (repairing once) and store an artifact, streaming the first draft."""
    started = time.perf_counter()
    brief_hash = _sha256(request.brief)
    log.set(artifact={"kind": request.kind.value, "brief_hash": brief_hash})
    try:
        async with asyncio.timeout(ARTIFACT_GENERATION_TIMEOUT_SECONDS):
            result = await _validated(request, on_delta)
    except TimeoutError as exc:
        raise _fail(request, ArtifactFailureReason.TIMEOUT, []) from exc
    except ArtifactRefusedError as exc:
        # the request is kept whole, so what tripped the filter can be read, not guessed
        log.warning(
            "artifact.refused",
            kind=request.kind.value,
            prompt_hash=_sha256(request.kind.value),
            input_hash=brief_hash,
            request_body=request.brief,
        )
        raise _fail(request, ArtifactFailureReason.REFUSED, []) from exc
    validation = result.validation
    if not validation.ok:
        raise _fail(request, ArtifactFailureReason.VALIDATION, validation.problems)

    artifact = await openui_artifact_repository.create(
        OpenUIArtifact(
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            kind=request.kind,
            title=title,
            program=validation.program,
            brief_hash=brief_hash,
            model=ARTIFACT_MODEL_NAME,
            repairs=result.repairs,
        )
    )
    total_ms = (time.perf_counter() - started) * 1000
    capture(
        UserId(request.user_id),
        ArtifactCreated(
            kind=request.kind.value,
            components=validation.components,
            repairs=result.repairs,
            output_tokens=result.output_tokens,
            first_component_ms=result.first_component_ms,
            total_ms=total_ms,
            model=ARTIFACT_MODEL_NAME,
        ),
    )
    log.set_ns(
        "artifact",
        id=artifact.id,
        status="created",
        repairs=result.repairs,
        components=validation.components,
        first_component_ms=result.first_component_ms,
        total_ms=total_ms,
    )
    return artifact
