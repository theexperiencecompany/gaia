"""validate_program: the request it sends the Node validator and what it makes of every way that ends."""

import asyncio
from collections.abc import Iterator
from contextlib import AbstractContextManager
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.openui_artifacts import ARTIFACT_VALIDATOR_TIMEOUT_SECONDS
from app.services.openui_artifacts import validate
from app.services.openui_artifacts.validate import (
    ArtifactValidation,
    ArtifactValidatorError,
    validate_program,
)

_NODE = "/usr/bin/node"
_VERDICT = {
    "ok": False,
    "program": "root = Artifact()",
    "problems": ["no root Artifact statement"],
    "resolved": {"callout1": "630 people"},
    "statements": 2,
    "components": 1,
}


def _process(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0) -> MagicMock:
    process = MagicMock(returncode=returncode)
    process.communicate = AsyncMock(return_value=(stdout, stderr))
    process.kill = MagicMock()
    process.wait = AsyncMock()
    return process


@pytest.fixture
def bundle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    built = tmp_path / "validate.cjs"
    built.write_text("")
    monkeypatch.setattr(validate, "ARTIFACT_VALIDATOR_BUNDLE", built)
    return built


@pytest.fixture
def node() -> Iterator[MagicMock]:
    with patch(f"{validate.__name__}.shutil.which", return_value=_NODE) as which:
        yield which


def _spawn(process: MagicMock) -> AbstractContextManager[AsyncMock]:
    return patch(
        f"{validate.__name__}.asyncio.create_subprocess_exec", AsyncMock(return_value=process)
    )


async def test_the_program_and_brief_go_to_the_bundle_on_stdin_and_its_verdict_comes_back(
    bundle: Path,
    node: MagicMock,
) -> None:
    process = _process(stdout=json.dumps(_VERDICT).encode())
    with _spawn(process) as spawn:
        verdict = await validate_program("reply text", "the brief", interactive=True)

    assert verdict == ArtifactValidation.model_validate(_VERDICT)
    node.assert_called_once_with("node")
    spawn.assert_awaited_once_with(
        _NODE,
        str(bundle),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    sent = json.loads(process.communicate.await_args.args[0])
    assert sent == {"program": "reply text", "brief": "the brief", "interactive": True}


@pytest.mark.usefixtures("node", "bundle")
async def test_a_valid_program_comes_back_ok_with_nothing_to_fix() -> None:
    clean = {**_VERDICT, "ok": True, "problems": []}
    with _spawn(_process(stdout=json.dumps(clean).encode())):
        verdict = await validate_program("r", "b", interactive=False)

    assert verdict.ok is True and verdict.problems == []


@pytest.mark.usefixtures("bundle")
async def test_without_node_the_error_says_what_to_install() -> None:
    with patch(f"{validate.__name__}.shutil.which", return_value=None):
        with pytest.raises(ArtifactValidatorError) as refused:
            await validate_program("r", "b", interactive=False)

    assert refused.value.message == "artifact validator is not installed"
    assert refused.value.why == "node=None, bundle exists=True"
    assert refused.value.fix == (
        "build tools/artifact-validate (nx run artifact-validate:build) and install node"
    )


@pytest.mark.usefixtures("node")
async def test_without_the_built_bundle_the_error_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(validate, "ARTIFACT_VALIDATOR_BUNDLE", tmp_path / "missing.cjs")

    with pytest.raises(ArtifactValidatorError) as refused:
        await validate_program("r", "b", interactive=False)

    assert refused.value.why == f"node={_NODE}, bundle exists=False"


@pytest.mark.usefixtures("node", "bundle")
async def test_a_validator_that_hangs_is_killed_and_reaped() -> None:
    process = _process()
    with (
        _spawn(process),
        patch(f"{validate.__name__}.asyncio.wait_for", AsyncMock(side_effect=TimeoutError)) as wait,
        pytest.raises(ArtifactValidatorError) as refused,
    ):
        await validate_program("r", "b", interactive=False)

    assert refused.value.message == "artifact validator timed out"
    assert wait.await_args.kwargs["timeout"] == ARTIFACT_VALIDATOR_TIMEOUT_SECONDS
    process.kill.assert_called_once_with()
    process.wait.assert_awaited_once_with()


@pytest.mark.usefixtures("node", "bundle")
async def test_a_crash_reports_the_exit_code_and_the_tail_of_stderr() -> None:
    stderr = b"x" * 2500 + b"boom"
    with _spawn(_process(stderr=stderr, returncode=3)), pytest.raises(ArtifactValidatorError) as e:
        await validate_program("r", "b", interactive=False)

    assert e.value.message == "artifact validator crashed"
    assert e.value.meta == {"returncode": 3, "stderr": stderr.decode()[-2000:]}
    assert str(e.value.meta["stderr"]).endswith("boom") and len(str(e.value.meta["stderr"])) == 2000


@pytest.mark.usefixtures("node", "bundle")
async def test_an_answer_that_is_not_a_verdict_is_a_malformed_output_error() -> None:
    stdout = b"y" * 2500 + b"{not json"
    with _spawn(_process(stdout=stdout)), pytest.raises(ArtifactValidatorError) as refused:
        await validate_program("r", "b", interactive=False)

    assert refused.value.message == "artifact validator returned malformed output"
    assert refused.value.meta == {"stdout": stdout.decode()[-2000:]}


@pytest.mark.usefixtures("node", "bundle")
async def test_a_verdict_missing_a_field_is_malformed_too() -> None:
    incomplete = {k: v for k, v in _VERDICT.items() if k != "problems"}
    with _spawn(_process(stdout=json.dumps(incomplete).encode())):
        with pytest.raises(ArtifactValidatorError, match="malformed output"):
            await validate_program("r", "b", interactive=False)
