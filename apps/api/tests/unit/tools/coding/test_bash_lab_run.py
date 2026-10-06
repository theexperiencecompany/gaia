"""bash run_todo_id: seed-then-run agent-lab launches on the existing bash tool.

Mocked-sandbox tests pin the wiring (gate order, seed-before-command, env
merge, the todo's run subscription, loud errors that run nothing). The fake-sandbox
test runs the REAL seed through local bash (proves it executes and stages
files) with an in-memory todos double — but it stops at _setup_lab_run: the
fake harness implements only the seed's call shape (cmd + timeout), not the
foreground/background streaming kwargs, so full-tool execution stays mocked.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from e2b import CommandExitException
import pytest
from tests.e2e._harness.fake_sandbox import FakeAsyncSandbox
from tests.e2e._harness.fake_todos import InMemoryTodos

from app.agents.tools.coding.bash_tool import _setup_lab_run, bash
from app.constants.sandbox import SANDBOX_USER_HOME
from app.constants.todos import FAILED_LABEL, GAIA_TRACKED_LABEL, TodoActivityEvent
from app.models.todo_models import TodoDocument, TodoUpdate
from app.models.trigger_subscription_models import SubscriptionAction
from app.services.agent_lab import agents_home, lab_runs, sandbox_setup
from app.services.agent_lab.lab_runs import run_dir
from app.services.agent_lab.sandbox_setup import (
    LAB_CALLBACK_URL_VAR,
    LAB_RUN_ID_VAR,
    LAB_TOKEN_VAR,
)
from app.services.analytics_service import AnalyticsEvents
from app.services.sandbox import execute_token

MODULE = "app.agents.tools.coding.bash_tool"
LAB_RUNS = "app.services.agent_lab.lab_runs"
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


def _todo(**overrides: object) -> TodoDocument:
    fields: dict[str, object] = {
        "id": "t1",
        "user_id": "u1",
        "title": "Lab task",
        "labels": [GAIA_TRACKED_LABEL],
    }
    fields.update(overrides)
    return TodoDocument(**fields)


@contextmanager
def _lab_stack(
    sbx: AsyncMock, todos: AsyncMock, *, lab_enabled: bool = True, todo: TodoDocument | None = None
) -> Iterator[AsyncMock]:
    """Patched gates for a lab run (flag, code mode off, repo, seed inputs); yields the activity mock.

    The same todos double stands behind the tool's lookup and lab_runs' subscribe write.
    """
    activity = AsyncMock(return_value=True)
    with ExitStack() as stack:
        stack.enter_context(patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)))
        stack.enter_context(patch(f"{MODULE}.sandbox_execute_enabled", return_value=False))
        stack.enter_context(
            patch(f"{MODULE}.is_agent_lab_enabled", new=AsyncMock(return_value=lab_enabled))
        )
        stack.enter_context(patch(f"{MODULE}.todo_repository", new=todos))
        stack.enter_context(patch(f"{LAB_RUNS}.todo_repository", new=todos))
        stack.enter_context(patch(f"{LAB_RUNS}.record_activity", new=activity))
        stack.enter_context(patch(f"{MODULE}.mint_lab_hooks_token", return_value="tok-lab"))
        stack.enter_context(patch(f"{MODULE}.lab_events_url", return_value=EVENTS_URL))
        todos.get = AsyncMock(return_value=todo)
        todos.update = AsyncMock(return_value=todo)
        yield activity


def _subscribed_run_id(todos: AsyncMock) -> str:
    update: TodoUpdate = todos.update.await_args.kwargs["update"]
    return str(update.trigger_subscriptions[-1].trigger_data[lab_runs.RUN_ID_KEY])


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

    @pytest.mark.parametrize(
        ("todo", "reason"),
        [
            (_todo(completed=True), "completed"),
            (_todo(labels=[GAIA_TRACKED_LABEL, FAILED_LABEL]), "failed"),
            (_todo(labels=[]), "not a tracked todo"),
        ],
        ids=["completed", "failed", "untracked"],
    )
    async def test_todo_that_cannot_be_woken_is_refused_and_runs_nothing(
        self, todo: TodoDocument, reason: str
    ) -> None:
        """Its events would 404 or be skipped, so the run would work on with nobody listening."""
        sbx = _sbx()
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=todo):
            out = await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        assert out.startswith("Error:") and reason in out and "ran nothing" in out
        assert sbx.commands.run.await_count == 0
        todos.update.assert_not_awaited()

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
        todos.update.assert_not_awaited()


@pytest.mark.unit
class TestLabHappyPath:
    async def test_seed_runs_first_then_command_gets_lab_env(self) -> None:
        sbx = _sbx(_ok("seeded"), _ok("hi"))
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=_todo()):
            out = await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        seed_call, cmd_call = sbx.commands.run.await_args_list
        run_id = _subscribed_run_id(todos)
        assert run_dir(run_id) in seed_call.args[0]
        assert "echo hi" not in seed_call.args[0]
        assert cmd_call.args[0] == "echo hi"

        envs = cmd_call.kwargs["envs"]
        assert envs[LAB_TOKEN_VAR] == "tok-lab"
        assert envs[LAB_CALLBACK_URL_VAR] == EVENTS_URL
        assert envs[LAB_RUN_ID_VAR] == run_id
        assert f"sandbox_run_id: {run_id}" in out

    async def test_watch_started_activity_line_is_posted(self) -> None:
        sbx = _sbx(_ok("seeded"), _ok("hi"))
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=_todo()) as activity:
            await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        assert activity.await_args.args[:3] == ("t1", "u1", TodoActivityEvent.WATCH_ADDED)
        assert _subscribed_run_id(todos) in activity.await_args.args[3]

    async def test_subscription_keeps_the_todos_existing_watches(self) -> None:
        sbx = _sbx(_ok("seeded"), _ok("hi"))
        todos = AsyncMock()
        existing = lab_runs.TriggerSubscription(
            trigger_name="gmail_new_message",
            action=SubscriptionAction.NOTIFY,
            resolution=lab_runs.SubscriptionResolution.ACCOUNT,
        )
        todo = _todo(trigger_subscriptions=[existing])
        with _lab_stack(sbx, todos, todo=todo):
            await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        names = [
            s.trigger_name for s in todos.update.await_args.kwargs["update"].trigger_subscriptions
        ]
        assert names == ["gmail_new_message", lab_runs.SANDBOX_RUN_TRIGGER]

    async def test_vanished_todo_at_subscribe_runs_nothing(self) -> None:
        sbx = _sbx(_ok("seeded"), _ok("hi"))
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=_todo()):
            todos.update = AsyncMock(return_value=None)
            out = await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        assert out.startswith("Error: subscribing todo t1")
        assert sbx.commands.run.await_count == 1

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
            patch(f"{LAB_RUNS}.todo_repository", new=todos),
            patch(f"{LAB_RUNS}.record_activity", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.mint_lab_hooks_token", return_value="tok-lab"),
            patch(f"{MODULE}.lab_events_url", return_value=EVENTS_URL),
        ):
            todos.get = AsyncMock(return_value=_todo())
            todos.update = AsyncMock(return_value=_todo())
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
        assert "sandbox_run_id:" in out
        todos.update.assert_awaited_once()


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
        todos = InMemoryTodos(todo)
        with (
            patch(f"{MODULE}.is_agent_lab_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.todo_repository", new=todos),
            patch(f"{LAB_RUNS}.todo_repository", new=todos),
            patch(f"{LAB_RUNS}.record_activity", new=AsyncMock(return_value=True)),
        ):
            lab = await _setup_lab_run(user_id="u1", run_todo_id="t1", sbx=fake)
        assert not isinstance(lab, str)
        assert lab.env[LAB_TOKEN_VAR]
        assert lab.env[LAB_CALLBACK_URL_VAR] == EVENTS_URL

        claims = execute_token.verify_execute_token(lab.env[LAB_TOKEN_VAR])
        assert claims.run_id == lab.run_id
        assert claims.user_id == "u1"
        assert claims.scoped_tool_names == []

        def _local(sandbox_path: str) -> Path:
            return Path(
                sandbox_path.replace(SANDBOX_USER_HOME, str(fake.root / "home")).replace(
                    "/workspace", str(fake.root)
                )
            )

        settings = json.loads(_local(lab.env["GAIA_LAB_CLAUDE_SETTINGS"]).read_text())
        commands = {
            handler["command"]
            for groups in settings["hooks"].values()
            for group in groups
            for handler in group["hooks"]
        }
        assert commands == {agents_home.HOOK_SCRIPT}
        assert os.access(_local(agents_home.HOOK_SCRIPT), os.X_OK)
        plugin = _local(lab.env["OPENCODE_CONFIG_DIR"]) / "plugins" / "gaia_notify.js"
        assert agents_home.HOOK_SCRIPT in plugin.read_text()
        # The token lives only in the run's private env file, never in shared config.
        for shared in (_local(lab.env["GAIA_LAB_CLAUDE_SETTINGS"]), plugin):
            assert lab.env[LAB_TOKEN_VAR] not in shared.read_text()
        assert run_dir(lab.run_id) == f"{SANDBOX_USER_HOME}/agents/runs/{lab.run_id}"

        lab_env_file = _local(sandbox_setup.lab_env_path(lab.run_id))
        sourced = await fake.commands.run(
            f"set -a; . {sandbox_setup.lab_env_path(lab.run_id)}; set +a; "
            "echo $GAIA_LAB_RUN_ID $OPENCODE_CONFIG_DIR"
        )
        assert oct(lab_env_file.stat().st_mode & 0o777) == "0o600"
        assert sourced.stdout.split() == [lab.run_id, lab.env["OPENCODE_CONFIG_DIR"]]

        (subscription,) = todo.trigger_subscriptions
        assert lab_runs.run_id_of(subscription) == lab.run_id


@pytest.mark.unit
class TestLabRunSubscribesTodo:
    async def test_run_todo_id_subscribes_the_todo_to_the_run(self) -> None:
        sbx = _sbx(_ok("seeded"), _ok("hi"))
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=_todo()):
            todos.update = AsyncMock(return_value=_todo())
            out = await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        update = todos.update.await_args.kwargs["update"]
        (subscription,) = update.trigger_subscriptions
        assert subscription.trigger_name == lab_runs.SANDBOX_RUN_TRIGGER
        assert subscription.action == SubscriptionAction.EXECUTE
        assert subscription.cooldown_seconds == 0
        run_id = subscription.trigger_data[lab_runs.RUN_ID_KEY]
        assert f"sandbox_run_id: {run_id}" in out

    async def test_subscribing_is_counted_for_the_todo_owner(self) -> None:
        sbx = _sbx(_ok("seeded"), _ok("hi"))
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=_todo()), patch(f"{LAB_RUNS}.capture_event") as capture:
            await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        distinct_id, event, props = capture.call_args.args
        assert distinct_id == "u1"
        assert event == AnalyticsEvents.TODO_SUBSCRIPTION_REGISTERED
        assert props["trigger_name"] == lab_runs.SANDBOX_RUN_TRIGGER

    async def test_command_env_points_both_clis_at_the_shared_hooks(self) -> None:
        """The CLI runs in its project folder, so hooks must load by path, not by cwd."""
        sbx = _sbx(_ok("seeded"), _ok("hi"))
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=_todo()):
            todos.update = AsyncMock(return_value=_todo())
            await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        envs = sbx.commands.run.await_args_list[1].kwargs["envs"]
        assert envs["OPENCODE_CONFIG_DIR"] == agents_home.OPENCODE_CONFIG_DIR
        assert envs["GAIA_LAB_CLAUDE_SETTINGS"] == agents_home.CLAUDE_SETTINGS_PATH
