"""Seed -> hook push -> todo woken, through a fake sandbox that really executes bash.

The bash tool's real run setup mints the token, runs the real seed script
through local bash and subscribes the todo; a hook-shaped body is then POSTed
with the token from the seeded env file to the real /lab/events route (fakeredis
budget), and the real fire_subscription queues the todo run. Only the leaves
are faked (see _harness/agent_lab.py). Not exercised: E2B boot, JuiceFS, the
CLIs actually firing their hooks.
"""

from __future__ import annotations

from httpx import AsyncClient
import pytest

from app.agents.tools.coding.bash_tool import _setup_lab_run
from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.todo_models import TodoDocument
from app.services.agent_lab import lab_runs
from tests.e2e._harness.agent_lab import lab_world, token_from_seeded_env
from tests.e2e._harness.fake_sandbox import FakeAsyncSandbox
from tests.e2e._harness.fake_todos import InMemoryTodos

pytestmark = pytest.mark.e2e


# Keys of a StopFailure body the real claude 2.1.286 POSTed from --settings (live capture).
_CLAUDE_STOP_FAILURE = {
    "session_id": "6f1c2b9e-4d1a-4a8e-9c2f-1b7e3d5a9c10",
    "transcript_path": "/home/user/.claude/projects/repo/6f1c.jsonl",
    "cwd": "/workspace/repo",
    "prompt_id": "c396e8ba-91ac-4b1e-9d3a-1f2e3d4c5b6a",
    "effort": {},
    "hook_event_name": "StopFailure",
    "error": "authentication_failed",
    "last_assistant_message": "Failed to authenticate. API Error: 401",
}
_CLAUDE_STOP = {
    "session_id": "6f1c2b9e-4d1a-4a8e-9c2f-1b7e3d5a9c10",
    "hook_event_name": "Stop",
    "transcript_path": "/home/user/.claude/projects/repo/6f1c.jsonl",
}


@pytest.mark.usefixtures("fake_redis")
@pytest.mark.parametrize(
    "hook_body", [_CLAUDE_STOP, _CLAUDE_STOP_FAILURE], ids=["stop", "stop-failure"]
)
async def test_claude_hook_push_wakes_the_todo_that_launched_the_run(
    client: AsyncClient, hook_body: dict[str, object]
) -> None:
    fake = FakeAsyncSandbox()
    todo = TodoDocument(id="t1", user_id="u-1", title="Fix flaky test", labels=[GAIA_TRACKED_LABEL])
    todos = InMemoryTodos(todo)

    with lab_world(todos) as enqueue:
        lab = await _setup_lab_run(user_id="u-1", run_todo_id="t1", sbx=fake)
        assert not isinstance(lab, str), lab
        token = await token_from_seeded_env(fake, lab.run_id)
        response = await client.post(
            "/api/v1/lab/events", json=hook_body, headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 202, response.text
    assert response.json() == {"ok": True, "run_id": lab.run_id}
    _, job, todo_id, origin = enqueue.await_args.args
    assert (job, todo_id) == ("execute_tracked_todo", "t1")
    assert origin.trigger_name == lab_runs.SANDBOX_RUN_TRIGGER
    assert origin.payload == {"kind": hook_body["hook_event_name"], "event": hook_body}


@pytest.mark.usefixtures("fake_redis")
async def test_opencode_plugin_push_wakes_the_todo(client: AsyncClient) -> None:
    fake = FakeAsyncSandbox()
    todos = InMemoryTodos(
        TodoDocument(id="t1", user_id="u-1", title="Fix flaky test", labels=[GAIA_TRACKED_LABEL])
    )
    plugin_body = {"kind": "permission", "raw": {"type": "permission.asked", "tool": "bash"}}

    with lab_world(todos) as enqueue:
        lab = await _setup_lab_run(user_id="u-1", run_todo_id="t1", sbx=fake)
        assert not isinstance(lab, str), lab
        token = await token_from_seeded_env(fake, lab.run_id)
        response = await client.post(
            "/api/v1/lab/events", json=plugin_body, headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 202, response.text
    assert enqueue.await_args.args[3].payload == {"kind": "permission", "event": plugin_body}


@pytest.mark.usefixtures("fake_redis")
async def test_push_after_the_todo_ended_is_404_and_wakes_nothing(client: AsyncClient) -> None:
    fake = FakeAsyncSandbox()
    todo = TodoDocument(id="t1", user_id="u-1", title="Fix flaky test", labels=[GAIA_TRACKED_LABEL])
    todos = InMemoryTodos(todo)

    with lab_world(todos) as enqueue:
        lab = await _setup_lab_run(user_id="u-1", run_todo_id="t1", sbx=fake)
        assert not isinstance(lab, str), lab
        token = await token_from_seeded_env(fake, lab.run_id)
        todo.completed = True
        response = await client.post(
            "/api/v1/lab/events",
            json={"hook_event_name": "Stop"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404
    enqueue.assert_not_awaited()
