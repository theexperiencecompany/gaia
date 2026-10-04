"""Agent-lab run world for e2e: the run path's leaves patched onto an in-memory todo store.

Real: the bash tool's run setup, the seed executing in a FakeAsyncSandbox, the
/lab/events route and fire_subscription. Faked: the todo store, entitlement
and flag reads, activity writes, analytics and the ARQ queue itself.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.agent_lab import lab_runs, sandbox_setup
from app.services.sandbox import execute_token
from tests.e2e._harness.fake_sandbox import FakeAsyncSandbox
from tests.e2e._harness.fake_todos import InMemoryTodos

EVENTS_URL = "https://gaia.test/api/v1/lab/events"
SECRET = "test-secret-" + "x" * 32


@contextmanager
def lab_world(todos: InMemoryTodos) -> Iterator[AsyncMock]:
    """Patch the leaves of the run path onto todos; yields the queue mock."""
    enqueue = AsyncMock()
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(sandbox_setup.settings, "SANDBOX_LAB_EVENTS_CALLBACK_URL", EVENTS_URL)
        )
        stack.enter_context(
            patch.object(execute_token.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", SECRET)
        )
        for target in (
            "app.agents.tools.coding.bash_tool.is_agent_lab_enabled",
            "app.services.agent_lab.lab_events.is_agent_lab_enabled",
        ):
            stack.enter_context(patch(target, AsyncMock(return_value=True)))
        stack.enter_context(
            patch("app.services.agent_lab.lab_events.is_paid", AsyncMock(return_value=True))
        )
        for module in (
            "app.agents.tools.coding.bash_tool",
            "app.services.agent_lab.lab_runs",
            "app.services.agent_lab.lab_events",
        ):
            stack.enter_context(patch(f"{module}.todo_repository", todos))
        stack.enter_context(
            patch("app.services.agent_lab.lab_runs.record_activity", AsyncMock(return_value=True))
        )
        dispatch = "app.services.triggers.subscription_dispatch"
        stack.enter_context(patch(f"{dispatch}.record_activity", AsyncMock(return_value=True)))
        stack.enter_context(patch(f"{dispatch}.capture_event", MagicMock()))
        stack.enter_context(patch(f"{dispatch}.enqueue_worker_job", enqueue))
        stack.enter_context(
            patch(f"{dispatch}.RedisPoolManager.get_pool", AsyncMock(return_value=MagicMock()))
        )
        yield enqueue


async def token_from_seeded_env(fake: FakeAsyncSandbox, run_id: str) -> str:
    """Read the token the way a hook would: by sourcing the seeded lab-env."""
    result = await fake.commands.run(
        f"set -a; . {lab_runs.run_dir(run_id)}/.gaia/lab-env; set +a; printf %s $GAIA_LAB_TOKEN"
    )
    return result.stdout
