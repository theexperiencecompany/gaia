"""Two concurrent lab runs stay isolated: each token only ever wakes its own todo.

Seeds two runs through the bash tool's real run setup into one FakeAsyncSandbox,
then interleaves byte-identical pushes on both tokens through the real
/lab/events route. Every push must queue exactly its own todo: the token alone
names the run, so identical bodies can neither cross over nor collapse.
"""

from __future__ import annotations

from httpx import AsyncClient
import pytest

from app.agents.tools.coding.bash_tool import _setup_lab_run
from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.todo_models import TodoDocument
from tests.e2e._harness.agent_lab import lab_world, token_from_seeded_env
from tests.e2e._harness.fake_sandbox import FakeAsyncSandbox
from tests.e2e._harness.fake_todos import InMemoryTodos

pytestmark = pytest.mark.e2e


@pytest.mark.usefixtures("fake_redis")
async def test_concurrent_runs_each_wake_only_their_own_todo(client: AsyncClient) -> None:
    fake = FakeAsyncSandbox()
    todos = InMemoryTodos(
        TodoDocument(id="t-a", user_id="u-1", title="First chore", labels=[GAIA_TRACKED_LABEL]),
        TodoDocument(id="t-b", user_id="u-1", title="Second chore", labels=[GAIA_TRACKED_LABEL]),
    )
    question = {"hook_event_name": "Notification", "message": "SAME-QUESTION"}
    finished = {"hook_event_name": "Stop"}

    with lab_world(todos) as enqueue:
        run_a = await _setup_lab_run(user_id="u-1", run_todo_id="t-a", sbx=fake)
        run_b = await _setup_lab_run(user_id="u-1", run_todo_id="t-b", sbx=fake)
        assert not isinstance(run_a, str), run_a
        assert not isinstance(run_b, str), run_b
        token_a = await token_from_seeded_env(fake, run_a.run_id)
        token_b = await token_from_seeded_env(fake, run_b.run_id)
        assert run_a.run_id != run_b.run_id and token_a != token_b

        for token, body in (
            (token_a, question),
            (token_b, question),
            (token_a, finished),
            (token_b, finished),
        ):
            response = await client.post(
                "/api/v1/lab/events", json=body, headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 202, response.text

    woken = [(call.args[2], call.args[3].payload["kind"]) for call in enqueue.await_args_list]
    assert woken == [
        ("t-a", "Notification"),
        ("t-b", "Notification"),
        ("t-a", "Stop"),
        ("t-b", "Stop"),
    ]
