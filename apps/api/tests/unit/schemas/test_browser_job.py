"""The ARQ job payload, its live state and its one ending survive the JSON round trips Redis and ARQ put them through."""

import pytest

from app.constants.browser import BrowserSessionStatus, JobEnding
from app.models.chat_models import ConversationSource
from app.schemas.browser import BrowserResultSnapshot
from app.schemas.browser_job import (
    BROWSER_JOB_ENDING,
    BrowserJobFinished,
    BrowserJobRequest,
    BrowserJobState,
    BrowserJobStatus,
    BrowserJobStopped,
)


@pytest.mark.unit
def test_request_round_trips_its_conversation_source_through_json() -> None:
    request = BrowserJobRequest(
        job_id="job-1",
        tool_call_id="call-1",
        user_id="user-1",
        conversation_id="conv-1",
        task="book a table",
        in_background=True,
        start_url="https://example.com",
        stream_id="stream-1",
        root_request_id="req-1",
        source_category="bot",
        conversation_source=ConversationSource.DISCORD,
    )
    restored = BrowserJobRequest.model_validate(request.model_dump(mode="json"))
    assert restored == request
    assert restored.conversation_source is ConversationSource.DISCORD


@pytest.mark.unit
def test_request_defaults_every_optional_field_to_none() -> None:
    request = BrowserJobRequest(
        job_id="job-1",
        tool_call_id="call-1",
        user_id="user-1",
        conversation_id="conv-1",
        task="book a table",
        in_background=False,
    )
    assert (request.start_url, request.stream_id, request.root_request_id) == (None, None, None)
    assert (request.source_category, request.conversation_source) == (None, None)


@pytest.mark.unit
def test_state_carries_who_its_ending_is_told_to() -> None:
    request = BrowserJobRequest(
        job_id="job-1",
        tool_call_id="call-1",
        user_id="user-1",
        conversation_id="conv-1",
        task="book a table",
        in_background=True,
    )

    state = BrowserJobState.of(request, BrowserJobStatus.RUNNING)

    assert BrowserJobState.model_validate(state.model_dump(mode="json")) == state
    assert (state.conversation_id, state.user_id, state.in_background) == ("conv-1", "user-1", True)


@pytest.mark.unit
@pytest.mark.parametrize(
    "ending",
    [
        BrowserJobFinished(
            result=BrowserResultSnapshot(
                status=BrowserSessionStatus.COMPLETED, success=True, summary="booked", steps=4
            )
        ),
        BrowserJobStopped(),
    ],
)
def test_an_ending_reads_back_as_the_ending_it_was(
    ending: BrowserJobFinished | BrowserJobStopped,
) -> None:
    restored = BROWSER_JOB_ENDING.validate_json(BROWSER_JOB_ENDING.dump_json(ending))

    assert restored == ending
    assert type(restored) is type(ending)


@pytest.mark.unit
def test_a_finished_ending_cannot_be_recorded_without_its_result() -> None:
    """The result lives only in the ending: one recorded without it could never be told."""
    with pytest.raises(ValueError, match="result"):
        BROWSER_JOB_ENDING.validate_python({"ending": JobEnding.FINISHED.value})


@pytest.mark.unit
def test_job_status_members_render_as_their_bare_value() -> None:
    """StrEnum, not (str, Enum): the status is interpolated into log lines."""
    assert f"{BrowserJobStatus.RUNNING}" == "running"
    assert {BrowserJobStatus.QUEUED: 1}.get("queued") == 1
