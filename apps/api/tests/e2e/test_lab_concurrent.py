"""Two concurrent lab runs stay isolated: tails, dedupe fingerprints, wakes.

Drives the REAL lab_start tool twice through one FakeAsyncSandbox (the real
build_seed_command output runs through a local bash, once per run), then
interleaves REAL record_lab_event calls across both sessions — including a
byte-identical kind+raw pair on both. Each todo's tail must carry its own
session id, and the wake must fire once per run: no cross-talk, and no
suppressed-duplicate false positive across different sessions (the event
fingerprint binds the session id, so identical payloads on two runs are two
events, not one re-POST).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.agents.tools.agent_lab_tools as lab_tools
from app.models.todo_models import TodoDocument, TodoUpdate
from app.services.agent_lab import sandbox_setup
import app.services.agent_lab.lab_events as lab_events_mod
from app.services.agent_lab.lab_events import LAB_TAIL_MARKER, record_lab_event
from tests.e2e._harness.fake_sandbox import FakeAsyncSandbox

pytestmark = pytest.mark.e2e

EVENTS_URL = "https://gaia.test/api/v1/lab/events"


class _AcquireCM:
    """Async CM yielding the fake sandbox (mirrors acquire_sandbox use)."""

    def __init__(self, sbx: Any) -> None:
        self._sbx = sbx

    async def __aenter__(self) -> Any:
        return self._sbx

    async def __aexit__(self, *args: Any) -> bool:
        return False


class _FakeTodos:
    """In-memory todo store for N runs: start writes refs, the relay resolves them."""

    def __init__(self, todos: list[TodoDocument]) -> None:
        self._by_id = {todo.id: todo for todo in todos}

    async def get(self, todo_id: str, user_id: str | None = None) -> TodoDocument | None:
        del user_id
        return self._by_id.get(todo_id)

    async def add_references(
        self, todo_id: str, *, user_id: str, references: list[str]
    ) -> TodoDocument | None:
        del user_id
        todo = self._by_id.get(todo_id)
        if todo is None:
            return None
        for ref in references:
            if ref not in todo.references:
                todo.references.append(ref)
        return todo

    async def find_by_reference(self, user_id: str, reference: str) -> TodoDocument | None:
        del user_id
        for todo in self._by_id.values():
            if reference in todo.references:
                return todo
        return None

    async def replace_note_fields(
        self,
        todo_id: str,
        user_id: str,
        *,
        update: TodoUpdate,
        expected_updated_at: Any = None,
    ) -> TodoDocument | None:
        del user_id, expected_updated_at
        todo = self._by_id.get(todo_id)
        if todo is None:
            return None
        if update.log_content is not None:
            todo.log_content = update.log_content
        return todo


def _bare_run_id(todo: TodoDocument) -> str:
    bare = [ref for ref in todo.references if not ref.startswith("lab:")]
    assert len(bare) == 1
    return bare[0]


def _config(user_id: str, thread_id: str) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": thread_id, "user_id": user_id},
        "metadata": {"user_id": user_id},
    }


async def test_concurrent_runs_keep_tails_and_wakes_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sandbox_setup.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", "test-secret-" + "x" * 32
    )
    monkeypatch.setattr(sandbox_setup.settings, "SANDBOX_LAB_EVENTS_CALLBACK_URL", EVENTS_URL)
    fake = FakeAsyncSandbox()
    todo_a = TodoDocument(id="t-a", user_id="u-1", title="First chore")
    todo_b = TodoDocument(id="t-b", user_id="u-1", title="Second chore")
    todos = _FakeTodos([todo_a, todo_b])
    start_activity = AsyncMock(return_value=True)

    with (
        patch.object(lab_tools, "is_agent_lab_enabled", new=AsyncMock(return_value=True)),
        patch.object(lab_tools, "todo_repository", new=todos),
        patch.object(lab_tools, "acquire_sandbox", new=MagicMock(return_value=_AcquireCM(fake))),
        patch.object(lab_tools, "record_activity", new=start_activity),
    ):
        result_a = await lab_tools.lab_start.ainvoke(
            {"task": "Do the first thing", "active_todo_id": "t-a"},
            config=_config("u-1", "lab-concurrent-a"),
        )
        result_b = await lab_tools.lab_start.ainvoke(
            {"task": "Do the second thing", "active_todo_id": "t-b"},
            config=_config("u-1", "lab-concurrent-b"),
        )
    assert "Lab run seeded" in result_a, result_a
    assert "Lab run seeded" in result_b, result_b
    run_a = _bare_run_id(todo_a)
    run_b = _bare_run_id(todo_b)
    assert run_a != run_b

    event_activity = AsyncMock(return_value=True)
    deliver = AsyncMock(return_value=None)
    with (
        patch.object(lab_events_mod, "is_paid", new=AsyncMock(return_value=True)),
        patch.object(lab_events_mod, "is_agent_lab_enabled", new=AsyncMock(return_value=True)),
        patch.object(lab_events_mod, "todo_repository", new=todos),
        patch.object(lab_events_mod, "record_activity", new=event_activity),
        patch.object(
            lab_events_mod,
            "load_user_context",
            new=AsyncMock(return_value=SimpleNamespace(id="u-1")),
        ),
        patch.object(lab_events_mod, "deliver_result_to_platforms", new=deliver),
    ):
        # Interleaved, byte-identical payloads on purpose: the same kind+raw
        # on two different sessions must file twice and wake twice.
        shared_question = {"message": "CONCURRENT-SAME-QUESTION"}
        receipt_a1 = await record_lab_event(
            run_a, user_id="u-1", kind="question", raw=shared_question
        )
        receipt_b1 = await record_lab_event(
            run_b, user_id="u-1", kind="question", raw=dict(shared_question)
        )
        receipt_a2 = await record_lab_event(run_a, user_id="u-1", kind="stop", raw={})
        receipt_b2 = await record_lab_event(run_b, user_id="u-1", kind="stop", raw={})

    assert (receipt_a1.todo_id, receipt_a2.todo_id) == ("t-a", "t-a")
    assert (receipt_b1.todo_id, receipt_b2.todo_id) == ("t-b", "t-b")
    assert receipt_a1.id == run_a
    assert receipt_b1.id == run_b

    content_a = todo_a.log_content or ""
    content_b = todo_b.log_content or ""
    for content in (content_a, content_b):
        assert LAB_TAIL_MARKER in content
    assert f"session {run_a}" in content_a
    assert f"session {run_b}" in content_b
    assert f"session {run_b}" not in content_a
    assert f"session {run_a}" not in content_b

    assert deliver.await_count == 4
    notes = [call.args[3] for call in event_activity.await_args_list]
    assert len(notes) == 4
    assert not any("duplicate suppressed" in note for note in notes)
