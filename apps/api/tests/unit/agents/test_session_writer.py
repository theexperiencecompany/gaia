"""A background run's stream writer: frames land in its session, a run of thinking as one entry."""

from collections.abc import Iterator
from unittest.mock import patch

import pytest

from app.agents.core.background.session import (
    RunKind,
    create_session,
    get_session,
    teardown_session,
)
from app.agents.core.background.session_writer import make_session_writer

pytestmark = pytest.mark.unit

STREAM = "writer-stream-1"
WRITER = "app.agents.core.background.session_writer"


@pytest.fixture(autouse=True)
def session() -> Iterator[None]:
    create_session(STREAM, RunKind.QUEUED)
    yield
    teardown_session(STREAM)


def test_thinking_deltas_without_text_join_into_the_text_that_follows() -> None:
    write = make_session_writer(STREAM)

    write({"reasoning": {"subagent_id": "s1"}})
    write({"reasoning": {"subagent_id": "s1", "content": "plan"}})
    write({"reasoning": {"subagent_id": "s1"}})

    session = get_session(STREAM)
    assert session is not None
    assert session.tool_events == [{"reasoning": {"subagent_id": "s1", "content": "plan"}}]


def test_the_first_frame_time_is_the_first_frames_alone() -> None:
    write = make_session_writer(STREAM)

    with patch(f"{WRITER}.time.perf_counter", side_effect=[1.5, 9.0]):
        write({"tool": "a"})
        write({"tool": "b"})

    session = get_session(STREAM)
    assert session is not None
    assert session.executor_first_frame_perf == 1.5
