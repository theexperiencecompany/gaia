"""The ARQ job payload and durable state survive the JSON round trip ARQ puts them through."""

import pytest

from app.constants.browser import BrowserSessionStatus
from app.models.chat_models import ConversationSource
from app.schemas.browser import BrowserResultSnapshot
from app.schemas.browser_job import BrowserJobRequest, BrowserJobState, BrowserJobStatus


@pytest.mark.unit
def test_request_round_trips_its_conversation_source_through_json() -> None:
    request = BrowserJobRequest(
        job_id="job-1",
        user_id="user-1",
        conversation_id="conv-1",
        task="book a table",
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
        job_id="job-1", user_id="user-1", conversation_id="conv-1", task="book a table"
    )
    assert (request.start_url, request.stream_id, request.root_request_id) == (None, None, None)
    assert (request.source_category, request.conversation_source) == (None, None)


@pytest.mark.unit
def test_state_round_trips_its_result_snapshot() -> None:
    state = BrowserJobState(
        job_id="job-1",
        status=BrowserJobStatus.DONE,
        task="book a table",
        session_id="sess-1",
        live_view_url="https://browser.example/abc",
        agent_message="Browser task completed.",
        result=BrowserResultSnapshot(
            status=BrowserSessionStatus.COMPLETED, success=True, summary="booked", steps=4
        ),
    )
    restored = BrowserJobState.model_validate(state.model_dump(mode="json"))
    assert restored == state
    assert restored.result is not None
    assert restored.result.summary == "booked"


@pytest.mark.unit
def test_state_starts_queued_with_no_session_and_no_result() -> None:
    state = BrowserJobState(job_id="job-1", status=BrowserJobStatus.QUEUED, task="book a table")
    assert state.session_id is None
    assert state.live_view_url is None
    assert state.agent_message is None
    assert state.result is None


@pytest.mark.unit
def test_job_status_members_render_as_their_bare_value() -> None:
    """StrEnum, not (str, Enum): the status is interpolated into log lines and guidance strings."""
    assert f"{BrowserJobStatus.RUNNING}" == "running"
    assert {BrowserJobStatus.DONE: 1}.get("done") == 1
