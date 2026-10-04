"""Two concurrent lab runs stay isolated: tails, dedupe fingerprints, wakes.

Seeds two runs directly with the REAL seeder through one FakeAsyncSandbox
(the real build_seed_command output runs through a local bash, once per run),
records each run id on its todo's references, then interleaves REAL
record_lab_event calls across both sessions — including a byte-identical
kind+raw pair on both. Each todo's tail must carry its own session id, and
the wake must fire once per run: no cross-talk, and no suppressed-duplicate
false positive across different sessions (the event fingerprint binds the
session id, so identical payloads on two runs are two events, not one
re-POST).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.models.todo_models import TodoDocument, TodoUpdate
from app.services.agent_lab import sandbox_setup
import app.services.agent_lab.lab_events as lab_events_mod
from app.services.agent_lab.lab_events import LAB_TAIL_MARKER, record_lab_event
from app.services.agent_lab.lab_runs import routing_ref, run_dir
from app.services.agent_lab.sandbox_setup import build_seed_command, mint_lab_hooks_token
from tests.e2e._harness.fake_sandbox import FakeAsyncSandbox

pytestmark = pytest.mark.e2e

EVENTS_URL = "https://gaia.test/api/v1/lab/events"


class _FakeTodos:
    """In-memory todo store for N runs: the seeder writes refs, the relay resolves them."""

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


async def _seed_run(fake: FakeAsyncSandbox, todos: _FakeTodos, todo_id: str) -> str:
    """Seed one run's workdir for real and record its ids on the todo; returns the run id."""
    run_id = uuid4().hex
    token = mint_lab_hooks_token("u-1", run_id)
    seed = build_seed_command(sandbox_setup.lab_events_url(), token, run_id, run_dir(run_id))
    await fake.commands.run(seed, timeout=300)
    await todos.add_references(
        todo_id, user_id="u-1", references=[run_id, routing_ref(run_id, uuid4().hex)]
    )
    return run_id


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

    run_a = await _seed_run(fake, todos, "t-a")
    run_b = await _seed_run(fake, todos, "t-b")
    assert run_a != run_b
    assert _bare_run_id(todo_a) == run_a
    assert _bare_run_id(todo_b) == run_b

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
