"""create_openui_artifact: one repair at most, fail loud with nothing stored, analytics on the outcome."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.openui_artifact_models import (
    ArtifactFailureReason,
    ArtifactKind,
    OpenUIArtifact,
)
from app.services.openui_artifacts.create import ArtifactCreationError, create_openui_artifact
from app.services.openui_artifacts.generate import (
    ArtifactRefusedError,
    ArtifactRequest,
    GeneratedReply,
)
from app.services.openui_artifacts.validate import ArtifactValidation
from shared.py.analytics import UserId
from shared.py.analytics.catalog.artifacts import ArtifactCreated, ArtifactFailed

_SVC = "app.services.openui_artifacts.create"
USER_ID = "6ad86cdfb9e7ae0b43a0efea"
REQUEST = ArtifactRequest(
    kind=ArtifactKind.DASHBOARD, brief="Sign-ups 1,840", user_id=USER_ID, conversation_id="c1"
)


def _reply(text: str, first_ms: float | None = 900.0) -> GeneratedReply:
    return GeneratedReply(
        text=text, input_tokens=10, cached_tokens=0, output_tokens=50, first_component_ms=first_ms
    )


def _verdict(program: str, problems: list[str]) -> ArtifactValidation:
    return ArtifactValidation(
        ok=not problems, program=program, problems=problems, resolved={}, statements=3, components=3
    )


@pytest.fixture
def capture() -> Iterator[MagicMock]:
    with patch(f"{_SVC}.capture") as mock:
        yield mock


@pytest.fixture
def repo() -> Iterator[MagicMock]:
    with patch(f"{_SVC}.openui_artifact_repository") as mock:
        mock.create = AsyncMock(side_effect=lambda doc: doc.model_copy(update={"id": "a1"}))
        yield mock


async def test_valid_first_draft_is_stored_without_a_repair(
    capture: MagicMock, repo: MagicMock
) -> None:
    with (
        patch(f"{_SVC}.write_program", AsyncMock(return_value=_reply("root = A"))),
        patch(f"{_SVC}.repair_program", AsyncMock()) as repair,
        patch(f"{_SVC}.validate_program", AsyncMock(return_value=_verdict("root = A", []))),
    ):
        artifact = await create_openui_artifact(REQUEST, "Atlas", AsyncMock())

    repair.assert_not_awaited()
    stored: OpenUIArtifact = repo.create.await_args.args[0]
    assert (stored.program, stored.repairs, stored.title) == ("root = A", 0, "Atlas")
    assert artifact.id == "a1"
    event = capture.call_args.args[1]
    assert capture.call_args.args[0] == UserId(USER_ID)
    assert isinstance(event, ArtifactCreated)
    assert (event.repairs, event.output_tokens, event.first_component_ms) == (0, 50, 900.0)


async def test_one_repair_fixes_the_program_and_is_counted(
    capture: MagicMock, repo: MagicMock
) -> None:
    verdicts = [_verdict("root = A", ["x is not in the source data"]), _verdict("root = B", [])]
    with (
        patch(f"{_SVC}.write_program", AsyncMock(return_value=_reply("root = A"))),
        patch(f"{_SVC}.repair_program", AsyncMock(return_value=_reply("root = B"))) as repair,
        patch(f"{_SVC}.validate_program", AsyncMock(side_effect=verdicts)),
    ):
        await create_openui_artifact(REQUEST, "Atlas", AsyncMock())

    assert repair.await_args.args[1:] == ("root = A", ["x is not in the source data"])
    stored: OpenUIArtifact = repo.create.await_args.args[0]
    assert (stored.program, stored.repairs) == ("root = B", 1)
    assert capture.call_args.args[1].output_tokens == 100


async def test_a_second_failure_stores_nothing_and_reports_the_problems(
    capture: MagicMock, repo: MagicMock
) -> None:
    bad = _verdict("root = A", ["p1", "p2"])
    with (
        patch(f"{_SVC}.write_program", AsyncMock(return_value=_reply("root = A"))),
        patch(f"{_SVC}.repair_program", AsyncMock(return_value=_reply("root = A"))) as repair,
        patch(f"{_SVC}.validate_program", AsyncMock(return_value=bad)),
        pytest.raises(ArtifactCreationError) as raised,
    ):
        await create_openui_artifact(REQUEST, "Atlas", AsyncMock())

    assert repair.await_count == 1
    repo.create.assert_not_awaited()
    assert (raised.value.reason, raised.value.problems) == (
        ArtifactFailureReason.VALIDATION,
        ["p1", "p2"],
    )
    capture.assert_called_once_with(
        UserId(USER_ID), ArtifactFailed(kind="dashboard", reason="validation", problem_count=2)
    )


async def test_a_refusal_fails_loud_without_a_retry(capture: MagicMock, repo: MagicMock) -> None:
    with (
        patch(f"{_SVC}.write_program", AsyncMock(side_effect=ArtifactRefusedError(message="no"))),
        patch(f"{_SVC}.repair_program", AsyncMock()) as repair,
        pytest.raises(ArtifactCreationError) as raised,
    ):
        await create_openui_artifact(REQUEST, "Atlas", AsyncMock())

    repair.assert_not_awaited()
    repo.create.assert_not_awaited()
    assert raised.value.reason is ArtifactFailureReason.REFUSED
    capture.assert_called_once_with(
        UserId(USER_ID), ArtifactFailed(kind="dashboard", reason="refused", problem_count=0)
    )
