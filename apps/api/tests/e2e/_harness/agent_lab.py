"""The sandbox a journey's coding-agent runs live in: real bash and files, no E2B.

Real: the bash tool's run setup, the seed executing in a FakeAsyncSandbox, the run token,
the /lab/events route and everything it wakes. Faked: E2B itself (acquire_sandbox hands
out the fake) and the AGENT_LAB flag, which is a PostHog read.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, patch

from app.config.settings import settings
from app.services.agent_lab import sandbox_setup
from tests.e2e._harness.fake_sandbox import FakeAsyncSandbox

EVENTS_URL = "https://gaia.test/api/v1/lab/events"
SECRET = "test-secret-" + "x" * 32
BASH_TOOL = "app.agents.tools.coding.bash_tool"


@contextmanager
def lab_sandbox(sandbox: FakeAsyncSandbox) -> Iterator[None]:
    """Serve sandbox to the bash tool, with run events configured and the AGENT_LAB flag on."""

    @asynccontextmanager
    async def acquire(user_id: str) -> AsyncIterator[FakeAsyncSandbox]:
        del user_id
        yield sandbox

    with ExitStack() as stack:
        stack.enter_context(patch.object(settings, "SANDBOX_LAB_EVENTS_CALLBACK_URL", EVENTS_URL))
        stack.enter_context(patch.object(settings, "SANDBOX_EXECUTE_TOKEN_SECRET", SECRET))
        stack.enter_context(
            patch(
                "app.services.agent_lab.lab_runs.is_agent_lab_enabled",
                AsyncMock(return_value=True),
            )
        )
        stack.enter_context(patch(f"{BASH_TOOL}.acquire_sandbox", acquire))
        yield


async def token_from_seeded_env(fake: FakeAsyncSandbox, run_id: str) -> str:
    """Read the token the way a hook would: by sourcing the seeded lab-env."""
    result = await fake.commands.run(
        f"set -a; . {sandbox_setup.lab_env_path(run_id)}; set +a; printf %s $GAIA_LAB_TOKEN"
    )
    return result.stdout
