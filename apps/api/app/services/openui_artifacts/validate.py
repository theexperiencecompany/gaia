"""Validate an artifact program with the web library's own validator (tools/artifact-validate).

The checks (parser arity, zod props, statement names, slot and number grounding, one program)
live once, in apps/web/src/features/artifacts/openui/validate.ts; this runs its Node bundle.
"""

import asyncio
import json
import shutil

from pydantic import BaseModel, ValidationError

from app.constants.openui_artifacts import (
    ARTIFACT_VALIDATOR_BUNDLE,
    ARTIFACT_VALIDATOR_TIMEOUT_SECONDS,
)
from app.utils.errors import AppError


class ArtifactValidation(BaseModel):
    """The validator's verdict on one program (ValidationResult in validate.ts)."""

    ok: bool
    program: str
    problems: list[str]
    resolved: dict[str, str]
    statements: int
    components: int


class ArtifactValidatorError(AppError):
    """The validator could not run: no node, no bundle, a crash or a malformed answer."""


async def validate_program(reply: str, brief: str) -> ArtifactValidation:
    """Extract the program from a model reply and run every check; problems are listed, not raised."""
    node = shutil.which("node")
    if node is None or not ARTIFACT_VALIDATOR_BUNDLE.exists():
        raise ArtifactValidatorError(
            message="artifact validator is not installed",
            why=f"node={node}, bundle exists={ARTIFACT_VALIDATOR_BUNDLE.exists()}",
            fix="build tools/artifact-validate (nx run artifact-validate:build) and install node",
        )
    process = await asyncio.create_subprocess_exec(
        node,
        str(ARTIFACT_VALIDATOR_BUNDLE),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    request = json.dumps({"program": reply, "brief": brief}).encode()
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(request), timeout=ARTIFACT_VALIDATOR_TIMEOUT_SECONDS
        )
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ArtifactValidatorError(message="artifact validator timed out") from exc
    if process.returncode != 0:
        raise ArtifactValidatorError(
            message="artifact validator crashed",
            meta={"returncode": process.returncode, "stderr": stderr.decode()[-2000:]},
        )
    try:
        return ArtifactValidation.model_validate_json(stdout)
    except ValidationError as exc:
        raise ArtifactValidatorError(
            message="artifact validator returned malformed output",
            meta={"stdout": stdout.decode()[-2000:]},
        ) from exc
