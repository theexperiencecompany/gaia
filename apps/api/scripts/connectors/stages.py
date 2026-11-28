"""The stages a connector is held to on one runner, each a real call through the production path.

A stage passes, fails with the observed reason, or is skipped with what it lacked; it never
passes on a guess. Calls with a real key go through run_with_secret exactly as the agent's
calls do. A call against a local fake adds the fake's endpoint to the call's environment and
is reported as a fake.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum

from app.models.connector_models import ConnectorKind, ConnectorSpec, IdentityExtractor
from app.services.connectors.commands import plan_call
from app.services.connectors.connect import extract_identity
from app.services.connectors.runner import ConnectorRunner
from app.services.connectors.service import (
    CallFailure,
    build_run_request,
    classify_failure,
    run_with_secret,
)

# Never a real key: the provider must refuse it, and GAIA must read the refusal as an auth failure.
BAD_KEY = "gaia_conformance_bad_key_0123456789abcdef"
_DETAIL_CHARS = 160


class Stage(StrEnum):
    SPEC = "spec valid"
    INSTALL = "install"
    BAD_KEY = "bad key refused"
    VERIFY = "verify"
    READ = "read"
    WRITE = "write+cleanup"


class Outcome(StrEnum):
    PASS = "pass"
    SKIP = "skip"
    FAIL = "fail"


@dataclass(frozen=True)
class StageResult:
    stage: Stage
    outcome: Outcome
    detail: str = ""


@dataclass(frozen=True)
class CallOutput:
    failure: CallFailure | None
    stdout: str
    stderr: str


@dataclass(frozen=True)
class Target:
    """Where one stage's calls go: a runner, a key, and the fake's endpoint env when it is a fake."""

    runner: ConnectorRunner
    secret: str
    fake_env: Mapping[str, str] | None = None
    fake_args: tuple[str, ...] = ()


def _short(text: str) -> str:
    return " ".join(text.split())[-_DETAIL_CHARS:]


def _why(output: CallOutput) -> str:
    return f"{output.failure}: {_short(output.stderr or output.stdout)}"


async def call(spec: ConnectorSpec, argv: list[str], target: Target) -> CallOutput:
    """Run one call the way the agent's run would, or against the fake when the target is one."""
    if target.fake_env is None:
        result = await run_with_secret(spec, argv, target.secret, runner=target.runner)
        return CallOutput(result.failure, result.stdout, result.stderr)
    request = build_run_request(spec, plan_call(spec, [*argv, *target.fake_args]), target.secret)
    raw = await target.runner.run(replace(request, env={**request.env, **target.fake_env}))
    return CallOutput(classify_failure(raw), raw.stdout, raw.stderr)


def _import_check(spec: ConnectorSpec) -> list[str]:
    modules = [p.name.replace("-", "_") for p in spec.install]
    return ["-c", f"import {', '.join(modules)}; print('imported')"]


async def install_stage(spec: ConnectorSpec, runner: ConnectorRunner) -> StageResult:
    """Install the pinned packages and run something that needs them, with a key that works nowhere."""
    match spec.kind:
        case ConnectorKind.REST:
            return StageResult(Stage.INSTALL, Outcome.SKIP, "REST: nothing to install")
        case ConnectorKind.CLI:
            argv = spec.usage.help_args
        case ConnectorKind.SDK:
            argv = _import_check(spec)
    output = await call(spec, argv, Target(runner, BAD_KEY))
    if output.failure is not None:
        return StageResult(Stage.INSTALL, Outcome.FAIL, _why(output))
    return StageResult(Stage.INSTALL, Outcome.PASS, " ".join(output.stdout.split())[:60])


async def bad_key_stage(
    spec: ConnectorSpec, runner: ConnectorRunner, bad_key: str = BAD_KEY
) -> StageResult:
    """Run the verify call with a key the provider has never issued; it must read as an auth failure."""
    output = await call(spec, spec.verify.args, Target(runner, bad_key))
    if output.failure is CallFailure.AUTH:
        return StageResult(Stage.BAD_KEY, Outcome.PASS, "refused as auth")
    return StageResult(Stage.BAD_KEY, Outcome.FAIL, _why(output))


async def verify_stage(
    spec: ConnectorSpec, target: Target, verify_args: list[str] | None = None
) -> StageResult:
    """Run the verify call with the real key and require the account it names."""
    output = await call(spec, verify_args or spec.verify.args, target)
    if output.failure is not None:
        return StageResult(Stage.VERIFY, Outcome.FAIL, _why(output))
    identity = extract_identity(spec.verify.identity, output.stdout)
    if not identity:
        return StageResult(
            Stage.VERIFY, Outcome.FAIL, f"no account named in: {_short(output.stdout)}"
        )
    return StageResult(Stage.VERIFY, Outcome.PASS, f"as {identity}")


async def read_stage(
    spec: ConnectorSpec, target: Target, argv: list[str], expect: str
) -> StageResult:
    """Run one read journey and require the expected text in its output."""
    output = await call(spec, argv, target)
    if output.failure is not None:
        return StageResult(Stage.READ, Outcome.FAIL, _why(output))
    if expect not in output.stdout:
        return StageResult(Stage.READ, Outcome.FAIL, f"{expect!r} not in: {_short(output.stdout)}")
    return StageResult(Stage.READ, Outcome.PASS, " ".join(argv)[:60])


@dataclass(frozen=True)
class WriteJourney:
    """Create one throwaway thing, delete it, and check the provider no longer has it."""

    create: list[str]
    cleanup: list[str]
    gone: list[str]
    # Where create's JSON names the new thing; None means its id is the {name} the run chose.
    id_path: str | None = None
    # A stateless fake answers every read the same, so it cannot show the deletion.
    stateful: bool = True


def _fill(argv: list[str], **values: str) -> list[str]:
    filled = []
    for arg in argv:
        for key, value in values.items():
            arg = arg.replace(f"{{{key}}}", value)
        filled.append(arg)
    return filled


async def write_stage(
    spec: ConnectorSpec, target: Target, journey: WriteJourney, name: str
) -> StageResult:
    """Create, clean up and confirm the deletion on the provider's side."""
    created = await call(spec, _fill(journey.create, name=name), target)
    if created.failure is not None:
        return StageResult(Stage.WRITE, Outcome.FAIL, f"create {_why(created)}")
    thing = (
        extract_identity(IdentityExtractor(json_path=journey.id_path), created.stdout)
        if journey.id_path
        else name
    )
    if not thing:
        return StageResult(Stage.WRITE, Outcome.FAIL, f"no id in: {_short(created.stdout)}")
    removed = await call(spec, _fill(journey.cleanup, id=thing, name=name), target)
    if removed.failure is not None:
        return StageResult(Stage.WRITE, Outcome.FAIL, f"cleanup of {thing} {_why(removed)}")
    if not journey.stateful:
        return StageResult(
            Stage.WRITE, Outcome.PASS, f"{thing} created and deleted (stateless fake)"
        )
    after = await call(spec, _fill(journey.gone, id=thing, name=name), target)
    if after.failure is None and thing in after.stdout:
        return StageResult(Stage.WRITE, Outcome.FAIL, f"{thing} still listed after cleanup")
    return StageResult(Stage.WRITE, Outcome.PASS, f"{thing} created, deleted, gone")
