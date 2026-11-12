"""create_openui_artifact: one repair at most, fail loud with nothing stored, analytics on the outcome."""

import asyncio
from collections.abc import Iterator
import hashlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.llm import ARTIFACT_MODEL_NAME
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
from tests.helpers import captured_wide_event

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


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


_INTERACTIVE = ArtifactRequest(
    kind=ArtifactKind.DASHBOARD,
    brief="Sign-ups 1,840",
    user_id=USER_ID,
    conversation_id="c1",
    interactive=True,
)


async def test_the_draft_is_written_for_the_request_and_checked_against_its_brief(
    capture: MagicMock, repo: MagicMock
) -> None:
    sink = AsyncMock()
    with (
        patch(f"{_SVC}.write_program", AsyncMock(return_value=_reply("draft"))) as write,
        patch(f"{_SVC}.validate_program", AsyncMock(return_value=_verdict("draft", []))) as check,
    ):
        await create_openui_artifact(_INTERACTIVE, "Atlas", sink)

    write.assert_awaited_once_with(_INTERACTIVE, sink)
    check.assert_awaited_once_with("draft", "Sign-ups 1,840", interactive=True)


async def test_the_repair_is_given_the_problems_and_its_answer_is_checked_the_same_way(
    capture: MagicMock, repo: MagicMock
) -> None:
    verdicts = [_verdict("draft", ["p1"]), _verdict("fixed", [])]
    with (
        patch(f"{_SVC}.write_program", AsyncMock(return_value=_reply("draft"))),
        patch(f"{_SVC}.repair_program", AsyncMock(return_value=_reply("fixed"))) as repair,
        patch(f"{_SVC}.validate_program", AsyncMock(side_effect=verdicts)) as check,
    ):
        async with captured_wide_event() as event:
            await create_openui_artifact(_INTERACTIVE, "Atlas", AsyncMock())

    repair.assert_awaited_once_with(_INTERACTIVE, "draft", ["p1"])
    assert check.await_args_list[1].args == ("fixed", "Sign-ups 1,840")
    assert check.await_args_list[1].kwargs == {"interactive": True}
    assert event["artifact"]["first_problems"] == ["p1"]


async def test_the_stored_artifact_records_who_what_and_how_it_was_made(
    capture: MagicMock, repo: MagicMock
) -> None:
    with (
        patch(f"{_SVC}.write_program", AsyncMock(return_value=_reply("root = A"))),
        patch(f"{_SVC}.validate_program", AsyncMock(return_value=_verdict("root = A", []))),
    ):
        await create_openui_artifact(REQUEST, "Atlas", AsyncMock())

    stored: OpenUIArtifact = repo.create.await_args.args[0]
    assert (stored.user_id, stored.conversation_id, stored.kind) == (
        USER_ID,
        "c1",
        ArtifactKind.DASHBOARD,
    )
    assert (stored.brief_hash, stored.model) == (_sha("Sign-ups 1,840"), ARTIFACT_MODEL_NAME)


async def test_the_success_is_counted_and_logged_with_its_timings(
    capture: MagicMock, repo: MagicMock
) -> None:
    with (
        patch(f"{_SVC}.write_program", AsyncMock(return_value=_reply("root = A"))),
        patch(f"{_SVC}.validate_program", AsyncMock(return_value=_verdict("root = A", []))),
        patch(f"{_SVC}.time.perf_counter", side_effect=[10.0, 10.5]),
    ):
        async with captured_wide_event() as event:
            await create_openui_artifact(REQUEST, "Atlas", AsyncMock())

    assert capture.call_args.args[1] == ArtifactCreated(
        kind="dashboard",
        components=3,
        repairs=0,
        output_tokens=50,
        first_component_ms=900.0,
        total_ms=500.0,
        model=ARTIFACT_MODEL_NAME,
    )
    assert event["artifact"] == {
        "kind": "dashboard",
        "brief_hash": _sha("Sign-ups 1,840"),
        "id": "a1",
        "status": "created",
        "repairs": 0,
        "components": 3,
        "first_component_ms": 900.0,
        "total_ms": 500.0,
    }


async def test_repairs_stop_at_the_limit_and_the_last_problems_are_reported(
    capture: MagicMock, repo: MagicMock
) -> None:
    problems = [f"p{i}" for i in range(25)]
    with (
        patch(f"{_SVC}.ARTIFACT_MAX_REPAIRS", 2),
        patch(f"{_SVC}.write_program", AsyncMock(return_value=_reply("draft"))),
        patch(f"{_SVC}.repair_program", AsyncMock(return_value=_reply("draft"))) as repair,
        patch(f"{_SVC}.validate_program", AsyncMock(return_value=_verdict("draft", problems))),
        pytest.raises(ArtifactCreationError) as raised,
    ):
        async with captured_wide_event() as event:
            await create_openui_artifact(REQUEST, "Atlas", AsyncMock())

    assert repair.await_count == 2
    assert raised.value.message == "the artifact could not be made (validation)"
    assert raised.value.meta == {"problems": problems[:20]}
    assert raised.value.problems == problems
    assert capture.call_args.args[1].problem_count == 25
    assert event["artifact"]["status"] == "failed"
    assert event["artifact"]["reason"] == "validation"
    assert event["artifact"]["problems"] == problems[:20]
    assert event["artifact"]["first_problems"] == problems[:20]


async def test_a_refusal_keeps_the_whole_request_in_the_log_for_reading(
    capture: MagicMock, repo: MagicMock
) -> None:
    with (
        patch(f"{_SVC}.write_program", AsyncMock(side_effect=ArtifactRefusedError(message="no"))),
        pytest.raises(ArtifactCreationError),
    ):
        async with captured_wide_event() as event:
            await create_openui_artifact(REQUEST, "Atlas", AsyncMock())

    [warning] = event["warnings"]
    assert warning["msg"] == "artifact.refused"
    assert warning["kind"] == "dashboard"
    assert warning["prompt_hash"] == _sha("dashboard")
    assert warning["input_hash"] == _sha("Sign-ups 1,840")
    assert warning["request_body"] == "Sign-ups 1,840"
    assert (event["artifact"]["status"], event["artifact"]["reason"]) == ("failed", "refused")


async def test_a_generation_past_its_time_limit_fails_as_a_timeout(
    capture: MagicMock, repo: MagicMock
) -> None:
    async def never(*_: Any) -> GeneratedReply:
        await asyncio.sleep(30)
        raise AssertionError("unreachable")

    with (
        patch(f"{_SVC}.ARTIFACT_GENERATION_TIMEOUT_SECONDS", 0.05),
        patch(f"{_SVC}.write_program", never),
        pytest.raises(ArtifactCreationError) as raised,
    ):
        await asyncio.wait_for(create_openui_artifact(REQUEST, "Atlas", AsyncMock()), timeout=5)

    assert raised.value.reason is ArtifactFailureReason.TIMEOUT
    repo.create.assert_not_awaited()
    capture.assert_called_once_with(
        UserId(USER_ID), ArtifactFailed(kind="dashboard", reason="timeout", problem_count=0)
    )
