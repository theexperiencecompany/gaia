"""bash run_todo_id: seed-then-run agent-lab launches on the existing bash tool.

Mocked-sandbox tests pin the wiring (gate order, seed-before-command, env
merge, references + activity, loud errors that run nothing). The fake-sandbox
test runs the REAL seed through local bash (proves it executes and stages
files) with an in-memory todos double — but it stops at _setup_lab_run: the
fake harness implements only the seed's call shape (cmd + timeout), not the
foreground/background streaming kwargs, so full-tool execution stays mocked.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from e2b import CommandExitException
import pytest
from tests.e2e._harness.fake_sandbox import FakeAsyncSandbox

from app.agents.tools.coding.bash_tool import _setup_lab_run, bash
from app.constants.todos import TodoActivityEvent
from app.models.todo_models import TodoDocument
from app.services.agent_lab import sandbox_setup
from app.services.agent_lab.lab_runs import routing_ref, run_dir
from app.services.agent_lab.sandbox_setup import (
    LAB_CALLBACK_URL_VAR,
    LAB_RUN_ID_VAR,
    LAB_SESSION_ID_VAR,
    LAB_TOKEN_VAR,
)
from app.services.sandbox import execute_token

MODULE = "app.agents.tools.coding.bash_tool"
CONFIG = {"configurable": {"user_id": "u1", "stream_id": "s1"}}
EVENTS_URL = "https://gaia.test/api/v1/lab/events"
SECRET = "unit-test-secret-0123456789abcdef0123456789abcdef"


def _sbx(*results: SimpleNamespace) -> AsyncMock:
    sbx = AsyncMock()
    sbx.sandbox_id = "sbx-9"
    sbx.commands = SimpleNamespace(run=AsyncMock(side_effect=list(results)))
    sbx.files = AsyncMock()
    return sbx


def _ok(stdout: str = "ok") -> SimpleNamespace:
    return SimpleNamespace(exit_code=0, stdout=stdout, stderr="")


def _acquire(sbx: AsyncMock) -> MagicMock:
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=sbx)
    manager.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=manager)


def _todo() -> TodoDocument:
    return TodoDocument(id="t1", user_id="u1", title="Lab task")


@contextmanager
def _lab_stack(
    sbx: AsyncMock, todos: AsyncMock, *, lab_enabled: bool = True, todo: TodoDocument | None = None
) -> Iterator[AsyncMock]:
    """Patched gates for a lab run (flag, code mode off, repo, seed inputs); yields the activity mock."""
    activity = AsyncMock(return_value=True)
    with ExitStack() as stack:
        stack.enter_context(patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)))
        stack.enter_context(patch(f"{MODULE}.sandbox_execute_enabled", return_value=False))
        stack.enter_context(
            patch(f"{MODULE}.is_agent_lab_enabled", new=AsyncMock(return_value=lab_enabled))
        )
        stack.enter_context(patch(f"{MODULE}.todo_repository", new=todos))
        stack.enter_context(patch(f"{MODULE}.record_activity", new=activity))
        stack.enter_context(patch(f"{MODULE}.mint_lab_hooks_token", return_value="tok-lab"))
        stack.enter_context(patch(f"{MODULE}.lab_events_url", return_value=EVENTS_URL))
        todos.get = AsyncMock(return_value=todo)
        if todo is not None:
            todos.add_references = AsyncMock(return_value=todo)
        yield activity


@pytest.mark.unit
class TestLabGate:
    async def test_flag_off_rejects_and_runs_nothing(self) -> None:
        sbx = _sbx()
        todos = AsyncMock()
        with _lab_stack(sbx, todos, lab_enabled=False):
            out = await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        assert out.startswith("Error: agent lab is disabled")
        assert sbx.commands.run.await_count == 0
        todos.get.assert_not_awaited()

    async def test_missing_todo_rejects_and_runs_nothing(self) -> None:
        sbx = _sbx()
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=None):
            out = await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        assert "t1" in out and "not found" in out
        assert sbx.commands.run.await_count == 0

    async def test_unresolvable_todo_id_rejects_loud(self) -> None:
        sbx = _sbx()
        todos = AsyncMock()
        todos.get = AsyncMock(side_effect=ValueError("not a todo id"))
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}.sandbox_execute_enabled", return_value=False),
            patch(f"{MODULE}.is_agent_lab_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.todo_repository", new=todos),
        ):
            out = await bash.ainvoke(
                {"command": "echo hi", "run_todo_id": "!!!"},
                config=CONFIG,
            )
        assert out.startswith("Error:")
        assert sbx.commands.run.await_count == 0

    async def test_seed_failure_runs_nothing_and_records_nothing(self) -> None:
        sbx = _sbx()
        sbx.commands.run = AsyncMock(
            side_effect=CommandExitException(stdout="", stderr="boom", exit_code=1, error=None)
        )
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=_todo()):
            out = await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        assert out.startswith("Error: lab seed failed")
        assert sbx.commands.run.await_count == 1
        todos.add_references.assert_not_awaited()


@pytest.mark.unit
class TestLabHappyPath:
    async def test_seed_runs_first_then_command_gets_lab_env(self) -> None:
        sbx = _sbx(_ok("seeded"), _ok("hi"))
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=_todo()):
            out = await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        seed_call, cmd_call = sbx.commands.run.await_args_list
        assert "GAIA_LAB_RUN_ID=" in seed_call.args[0]
        assert "echo hi" not in seed_call.args[0]
        assert cmd_call.args[0] == "echo hi"

        run_id = todos.add_references.await_args.kwargs["references"][0]
        envs = cmd_call.kwargs["envs"]
        assert envs[LAB_TOKEN_VAR] == "tok-lab"
        assert envs[LAB_CALLBACK_URL_VAR] == EVENTS_URL
        assert envs[LAB_SESSION_ID_VAR] == run_id
        assert envs[LAB_RUN_ID_VAR] == run_id
        assert f"lab_run_id: {run_id}" in out

    async def test_references_carry_bare_id_plus_routing_ref(self) -> None:
        """Bare id resolves event pushes; the routing ref marks the todo as a lab run for keepwarm."""
        sbx = _sbx(_ok("seeded"), _ok("hi"))
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=_todo()):
            await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        (run_id, routing) = todos.add_references.await_args.kwargs["references"]
        assert routing == routing_ref(run_id, run_id)
        assert run_dir(run_id).startswith("/workspace/.gaia/lab/")

    async def test_started_activity_line_is_posted(self) -> None:
        sbx = _sbx(_ok("seeded"), _ok("hi"))
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=_todo()) as activity:
            await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        assert activity.await_args.args[:3] == ("t1", "u1", TodoActivityEvent.RUN_STARTED)
        assert "lab run" in activity.await_args.args[3]

    async def test_lab_env_merges_with_code_mode_env(self) -> None:
        sbx = _sbx(_ok("seeded"), _ok("hi"))
        todos = AsyncMock()
        with (
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
            patch(f"{MODULE}.sandbox_execute_enabled", return_value=True),
            patch(f"{MODULE}.is_code_mode_enabled", return_value=True),
            patch(f"{MODULE}.seed_execute_client", new=AsyncMock()),
            patch(f"{MODULE}.mint_execute_env", return_value={"GAIA_EXECUTE_TOKEN": "tok-exec"}),
            patch(f"{MODULE}.is_agent_lab_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.todo_repository", new=todos),
            patch(f"{MODULE}.record_activity", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.mint_lab_hooks_token", return_value="tok-lab"),
            patch(f"{MODULE}.lab_events_url", return_value=EVENTS_URL),
        ):
            todos.get = AsyncMock(return_value=_todo())
            todos.add_references = AsyncMock(return_value=_todo())
            await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        envs = sbx.commands.run.await_args_list[1].kwargs["envs"]
        assert envs["GAIA_EXECUTE_TOKEN"] == "tok-exec"
        assert envs[LAB_TOKEN_VAR] == "tok-lab"

    async def test_background_lab_run_seeds_first_then_detaches(self) -> None:
        sbx = _sbx(_ok("seeded"), _ok("777\n"))
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=_todo()):
            out = await bash.ainvoke(
                {"command": "sleep 99", "background": True, "run_todo_id": "t1"},
                config=CONFIG,
            )
        assert sbx.commands.run.await_count == 2
        assert "pid=777" in out
        assert "lab_run_id:" in out
        todos.add_references.assert_awaited_once()


class _MemTodos:
    """In-memory todos double: the seed writes refs here, the asserts read them."""

    def __init__(self, doc: TodoDocument) -> None:
        self._doc = doc

    async def get(self, todo_id: str, *, user_id: str | None = None) -> TodoDocument | None:
        del user_id
        return self._doc if self._doc.id == todo_id else None

    async def add_references(
        self, todo_id: str, *, user_id: str, references: list[str]
    ) -> TodoDocument | None:
        del user_id
        if self._doc.id != todo_id:
            return None
        for ref in references:
            if ref not in self._doc.references:
                self._doc.references.append(ref)
        return self._doc


@pytest.mark.unit
class TestLabSeedExecutes:
    async def test_real_seed_stages_files_and_env_resolves_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Real mint + real seed script through local bash; env visibly reaches a command."""
        monkeypatch.setattr(sandbox_setup.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", SECRET)
        monkeypatch.setattr(execute_token.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", SECRET)
        monkeypatch.setattr(sandbox_setup.settings, "SANDBOX_LAB_EVENTS_CALLBACK_URL", EVENTS_URL)
        fake = FakeAsyncSandbox()
        todo = _todo()
        with (
            patch(f"{MODULE}.is_agent_lab_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.todo_repository", new=_MemTodos(todo)),
            patch(f"{MODULE}.record_activity", new=AsyncMock(return_value=True)),
        ):
            lab = await _setup_lab_run(user_id="u1", run_todo_id="t1", sbx=fake)
        assert not isinstance(lab, str)
        assert lab.env[LAB_TOKEN_VAR]
        assert lab.env[LAB_CALLBACK_URL_VAR] == EVENTS_URL

        claims = execute_token.verify_execute_token(lab.env[LAB_TOKEN_VAR])
        assert claims.run_id == lab.run_id
        assert claims.user_id == "u1"
        assert claims.scoped_tool_names == []

        root = fake.root / ".gaia" / "lab" / lab.run_id
        assert (root / ".claude" / "settings.json").is_file()
        assert EVENTS_URL in (root / ".claude" / "settings.json").read_text()
        assert (root / ".gaia" / "lab-env").is_file()
        assert (root / ".opencode" / "plugins" / "gaia_lab_notify.js").is_file()
        assert run_dir(lab.run_id) == f"/workspace/.gaia/lab/{lab.run_id}"

        probe = await fake.commands.run("echo $GAIA_LAB_RUN_ID", envs=lab.env)
        assert lab.run_id in probe.stdout

        assert lab.run_id in todo.references
        assert routing_ref(lab.run_id, lab.run_id) in todo.references
