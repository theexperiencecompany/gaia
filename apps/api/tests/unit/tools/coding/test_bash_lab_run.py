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
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from e2b import CommandExitException
import pytest
from tests.e2e._harness.fake_sandbox import FakeAsyncSandbox
from tests.e2e._harness.fake_todos import InMemoryTodos, with_watch
import time_machine

from app.agents.tools.coding.bash_tool import _setup_lab_run, bash, build_bash_tool
from app.constants.execute import SANDBOX_LAB_MAX_RUN_SECONDS
from app.constants.sandbox import SANDBOX_USER_HOME
from app.constants.todos import FAILED_LABEL, GAIA_TRACKED_LABEL, TodoActivityEvent
from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import SubscriptionAction, TriggerSubscription
from app.services.agent_lab import agents_home, lab_runs, sandbox_setup
from app.services.agent_lab.lab_runs import (
    LAB_SEED_TIMEOUT_SECONDS,
    LabAccess,
    RunCapStatus,
    run_dir,
)
from app.services.agent_lab.sandbox_setup import (
    LAB_CALLBACK_URL_VAR,
    LAB_RUN_ID_VAR,
    LAB_TOKEN_VAR,
    build_seed_command,
    lab_env_path,
)
from app.services.sandbox import execute_token
from app.services.sandbox.local_sandbox import LocalDockerSandbox
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.todos import TodosSubscriptionRegistered

# A real ObjectId: analytics refuses anything that is not a GAIA user id.
USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.coding.bash_tool"
LAB_RUNS = "app.services.agent_lab.lab_runs"
SUBSCRIPTIONS = "app.services.triggers.subscription_service"
CONFIG = {"configurable": {"user_id": USER_ID, "stream_id": "s1"}}
SESSION_CONFIG = {"configurable": {"user_id": USER_ID, "conversation_id": "conv1"}}
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
        "user_id": USER_ID,
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
            patch(f"{LAB_RUNS}.is_agent_lab_enabled", new=AsyncMock(return_value=lab_enabled))
        )
        stack.enter_context(patch(f"{LAB_RUNS}.is_paid", new=AsyncMock(return_value=True)))
        stack.enter_context(patch(f"{MODULE}.todo_repository", new=todos))
        stack.enter_context(patch(f"{LAB_RUNS}.todo_repository", new=todos))
        stack.enter_context(patch(f"{SUBSCRIPTIONS}.todo_repository", new=todos))
        stack.enter_context(patch(f"{SUBSCRIPTIONS}.record_activity", new=activity))
        stack.enter_context(patch(f"{MODULE}.mint_lab_hooks_token", return_value="tok-lab"))
        stack.enter_context(patch(f"{MODULE}.lab_events_url", return_value=EVENTS_URL))
        todos.get = AsyncMock(return_value=todo)
        todos.add_trigger_subscription = _appending(todo)
        yield activity


def _appending(todo: TodoDocument | None) -> AsyncMock:
    """Stand in for the repository's append: the todo with the watch on it, None once it is gone."""

    def add(
        _todo_id: str, *, user_id: str, subscription: TriggerSubscription
    ) -> TodoDocument | None:
        return None if todo is None else with_watch(todo, subscription)

    return AsyncMock(side_effect=add)


def _subscribed(todos: AsyncMock) -> TriggerSubscription:
    return todos.add_trigger_subscription.await_args.kwargs["subscription"]


def _subscribed_run_id(todos: AsyncMock) -> str:
    return str(_subscribed(todos).trigger_data[lab_runs.RUN_ID_KEY])


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

    async def test_a_local_docker_sandbox_refuses_the_run_and_runs_nothing(self) -> None:
        # Self-host's local containers have neither the E2B agents' home nor the CLI installers' curl.
        sbx = MagicMock(spec=LocalDockerSandbox)
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=_todo()):
            out = await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        assert out.startswith("Error: sandbox agent runs (run_todo_id) need the hosted E2B")
        sbx.commands.run.assert_not_called()
        todos.get.assert_not_awaited()
        todos.add_trigger_subscription.assert_not_awaited()

    async def test_a_flagged_user_off_the_paid_plan_launches_nothing(self) -> None:
        # launch checked only the flag while the event receiver also
        # requires Pro, so the run's every event got 402 and its todo never heard.
        sbx = _sbx()
        todos = AsyncMock()
        with (
            _lab_stack(sbx, todos, todo=_todo()),
            patch(f"{LAB_RUNS}.is_paid", AsyncMock(return_value=False), create=True),
        ):
            out = await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        assert out.startswith("Error:") and "paid plan" in out
        assert sbx.commands.run.await_count == 0
        todos.add_trigger_subscription.assert_not_awaited()

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
            patch(f"{LAB_RUNS}.is_agent_lab_enabled", new=AsyncMock(return_value=True)),
            patch(f"{LAB_RUNS}.is_paid", new=AsyncMock(return_value=True)),
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
        todos.add_trigger_subscription.assert_not_awaited()

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
        todos.add_trigger_subscription.assert_not_awaited()


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
        assert activity.await_args.args[:3] == ("t1", USER_ID, TodoActivityEvent.WATCH_ADDED)
        assert _subscribed_run_id(todos) in activity.await_args.args[3]

    async def test_vanished_todo_at_subscribe_runs_nothing(self) -> None:
        sbx = _sbx(_ok("seeded"), _ok("hi"))
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=_todo()):
            todos.add_trigger_subscription = AsyncMock(return_value=None)
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
            patch(f"{LAB_RUNS}.is_agent_lab_enabled", new=AsyncMock(return_value=True)),
            patch(f"{LAB_RUNS}.is_paid", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.todo_repository", new=todos),
            patch(f"{LAB_RUNS}.todo_repository", new=todos),
            patch(f"{SUBSCRIPTIONS}.todo_repository", new=todos),
            patch(f"{SUBSCRIPTIONS}.record_activity", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.mint_lab_hooks_token", return_value="tok-lab"),
            patch(f"{MODULE}.lab_events_url", return_value=EVENTS_URL),
        ):
            todos.get = AsyncMock(return_value=_todo())
            todos.add_trigger_subscription = _appending(_todo())
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
        todos.add_trigger_subscription.assert_awaited_once()


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
            patch(f"{LAB_RUNS}.is_agent_lab_enabled", new=AsyncMock(return_value=True)),
            patch(f"{LAB_RUNS}.is_paid", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.todo_repository", new=todos),
            patch(f"{LAB_RUNS}.todo_repository", new=todos),
            patch(f"{SUBSCRIPTIONS}.todo_repository", new=todos),
            patch(f"{SUBSCRIPTIONS}.record_activity", new=AsyncMock(return_value=True)),
        ):
            lab = await _setup_lab_run(user_id=USER_ID, run_todo_id="t1", sbx=fake)
        assert not isinstance(lab, str)
        assert lab.env[LAB_TOKEN_VAR]
        assert lab.env[LAB_CALLBACK_URL_VAR] == EVENTS_URL

        claims = execute_token.verify_execute_token(lab.env[LAB_TOKEN_VAR])
        assert claims.run_id == lab.run_id
        assert claims.user_id == USER_ID
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
class TestFailedLaunchUnsubscribes:
    async def test_a_background_launch_that_never_starts_leaves_no_subscription(self) -> None:
        # the todo subscribed before the launch and stayed subscribed
        # when it failed, so a run that never existed counted as live.
        sbx = _sbx(_ok("seeded"), SimpleNamespace(exit_code=0, stdout="", stderr="no shell"))
        todos = InMemoryTodos(_todo())
        with (
            _lab_stack(sbx, AsyncMock(), todo=_todo()),
            patch(f"{MODULE}.todo_repository", new=todos),
            patch(f"{LAB_RUNS}.todo_repository", new=todos),
            patch(f"{SUBSCRIPTIONS}.todo_repository", new=todos),
            patch(f"{SUBSCRIPTIONS}.record_activity", AsyncMock()),
        ):
            out = await bash.ainvoke(
                {"command": "claude -p hi", "run_todo_id": "t1", "background": True},
                config=CONFIG,
            )
        assert "failed to start background command" in out
        assert "sandbox_run_id" not in out
        stored = await todos.get("t1", user_id=USER_ID)
        assert stored is not None
        assert lab_runs.run_subscriptions(stored) == []

    async def test_a_background_start_failure_is_a_command_error_not_a_sandbox_crash(
        self,
    ) -> None:
        # it raised through acquire_sandbox, so the sandbox was
        # health-checked as if it had died and the tool logged a crash.
        sbx = _sbx(SimpleNamespace(exit_code=0, stdout="", stderr="no shell"))
        acquire = _acquire(sbx)
        error_log = MagicMock()
        with (
            patch(f"{MODULE}.acquire_sandbox", new=acquire),
            patch(f"{MODULE}.sandbox_execute_enabled", return_value=False),
            patch(f"{MODULE}.log.error", error_log),
        ):
            out = await bash.ainvoke({"command": "sleep 60", "background": True}, config=CONFIG)
        assert out == "Error: failed to start background command (stderr: no shell)"
        exc_type = acquire.return_value.__aexit__.await_args.args[0]
        assert exc_type is None, "the start failure reached the sandbox's crash handling"
        error_log.assert_not_called()


@pytest.mark.unit
class TestLabRunSubscribesTodo:
    async def test_run_todo_id_subscribes_the_todo_to_the_run(self) -> None:
        sbx = _sbx(_ok("seeded"), _ok("hi"))
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=_todo()):
            out = await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        subscription = _subscribed(todos)
        assert subscription.trigger_name == lab_runs.SANDBOX_RUN_TRIGGER
        assert subscription.action == SubscriptionAction.EXECUTE
        assert subscription.cooldown_seconds == 0
        run_id = subscription.trigger_data[lab_runs.RUN_ID_KEY]
        assert f"sandbox_run_id: {run_id}" in out

    async def test_subscribing_is_counted_for_the_todo_owner(self) -> None:
        sbx = _sbx(_ok("seeded"), _ok("hi"))
        todos = AsyncMock()
        with (
            _lab_stack(sbx, todos, todo=_todo()),
            patch(f"{SUBSCRIPTIONS}.capture") as capture,
        ):
            await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        distinct_id, event = capture.call_args.args
        assert distinct_id == UserId(USER_ID)
        assert isinstance(event, TodosSubscriptionRegistered)
        assert event.trigger_name == lab_runs.SANDBOX_RUN_TRIGGER

    async def test_command_env_points_both_clis_at_the_shared_hooks(self) -> None:
        """The CLI runs in its project folder, so hooks must load by path, not by cwd."""
        sbx = _sbx(_ok("seeded"), _ok("hi"))
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=_todo()):
            await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        envs = sbx.commands.run.await_args_list[1].kwargs["envs"]
        assert envs["OPENCODE_CONFIG_DIR"] == agents_home.OPENCODE_CONFIG_DIR
        assert envs["GAIA_LAB_CLAUDE_SETTINGS"] == agents_home.CLAUDE_SETTINGS_PATH


@pytest.mark.unit
class TestLabRunToolContract:
    async def test_a_lab_run_returns_the_command_output_then_the_runs_footer(self) -> None:
        sbx = _sbx(_ok("seeded"), _ok("hi"))
        todos = AsyncMock()
        with _lab_stack(sbx, todos, todo=_todo()):
            out = await build_bash_tool().ainvoke(
                {"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG
            )
        run_id = _subscribed_run_id(todos)
        assert out == (
            "exit_code: 0\n\nstdout:\nhi\n"
            f"sandbox_run_id: {run_id} (GAIA_LAB_* and OPENCODE_CONFIG_DIR injected; a later "
            f"resume sources {lab_env_path(run_id)}). "
            "Todo t1 is now subscribed to this run: every event the agent "
            "reports (finished, needs input, error) runs the todo with that event.\n"
            "Record the pid and log path on the todo's canvas so later runs can find the log."
        )

    async def test_the_seed_is_built_for_this_run_and_user_and_runs_with_the_seed_deadline(
        self,
    ) -> None:
        sbx = _sbx(_ok("seeded"), _ok("hi"))
        todos = AsyncMock()
        with (
            _lab_stack(sbx, todos, todo=_todo()),
            patch(f"{MODULE}.mint_lab_hooks_token", return_value="tok-lab") as mint,
        ):
            await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        run_id = _subscribed_run_id(todos)
        seed_call = sbx.commands.run.await_args_list[0]
        assert seed_call == call(
            build_seed_command(EVENTS_URL, "tok-lab", run_id), timeout=LAB_SEED_TIMEOUT_SECONDS
        )
        mint.assert_called_once_with(USER_ID, run_id)
        assert todos.get.await_args_list[0] == call("t1", user_id=USER_ID)

    async def test_lab_access_is_checked_for_the_invoking_user(self) -> None:
        sbx = _sbx()
        todos = AsyncMock()
        access = AsyncMock(return_value=LabAccess.FLAG_OFF)
        with _lab_stack(sbx, todos, todo=_todo()), patch(f"{MODULE}.lab_access", new=access):
            out = await bash.ainvoke({"command": "echo hi", "run_todo_id": "t1"}, config=CONFIG)
        assert out == (
            "Error: agent lab is disabled for this user (run_todo_id needs the AGENT_LAB flag)"
        )
        access.assert_awaited_once_with(USER_ID)

    async def test_a_refused_lab_run_ends_its_stream_with_the_error(self) -> None:
        sbx = _sbx()
        todos = AsyncMock()
        with (
            _lab_stack(sbx, todos, lab_enabled=False),
            patch(f"{MODULE}.safe_emit") as emit,
        ):
            out = await bash.ainvoke(
                {"command": "echo hi", "run_todo_id": "t1"}, config=SESSION_CONFIG
            )
        run_id = emit.call_args_list[0].args[0]["bash_data"]["id"]
        error = {"id": run_id, "status": "error", "exit_code": None, "stream": "stderr"}
        assert emit.call_args_list[-1] == call(
            {"bash_data": {**error, "chunk": out}}, session_id="conv1"
        )

    async def test_a_launch_that_never_starts_unsubscribes_the_invoking_users_todo(
        self,
    ) -> None:
        sbx = _sbx(_ok("seeded"), SimpleNamespace(exit_code=0, stdout="", stderr="no shell"))
        todos = AsyncMock()
        unregister = AsyncMock()
        with (
            _lab_stack(sbx, todos, todo=_todo()),
            patch(f"{MODULE}.unregister_subscription", new=unregister),
        ):
            await bash.ainvoke(
                {"command": "sleep 9", "run_todo_id": "t1", "background": True}, config=CONFIG
            )
        unregister.assert_awaited_once_with("t1", USER_ID, _subscribed(todos).id)


@pytest.mark.unit
class TestLabRuns:
    async def test_lab_access_checks_the_plan_and_the_flag_for_that_user(self) -> None:
        paid = AsyncMock(return_value=True)
        flag = AsyncMock(return_value=True)
        with (
            patch(f"{LAB_RUNS}.is_paid", new=paid),
            patch(f"{LAB_RUNS}.is_agent_lab_enabled", new=flag),
        ):
            access = await lab_runs.lab_access(USER_ID)
        assert access == LabAccess.ALLOWED
        paid.assert_awaited_once_with(USER_ID)
        flag.assert_awaited_once_with(USER_ID)

    @pytest.mark.parametrize(
        ("age_seconds", "expected"),
        [
            (SANDBOX_LAB_MAX_RUN_SECONDS, RunCapStatus(live=True, capped_todo_ids=[])),
            (SANDBOX_LAB_MAX_RUN_SECONDS + 1, RunCapStatus(live=False, capped_todo_ids=["t1"])),
        ],
        ids=["at-cap", "past-cap"],
    )
    def test_a_run_is_live_up_to_and_including_the_cap(
        self, age_seconds: int, expected: RunCapStatus
    ) -> None:
        now = datetime(2026, 1, 1, 12, tzinfo=UTC)
        watch = lab_runs.TriggerSubscription(
            trigger_name=lab_runs.SANDBOX_RUN_TRIGGER,
            action=SubscriptionAction.EXECUTE,
            resolution=lab_runs.SubscriptionResolution.ACCOUNT,
            trigger_data={lab_runs.RUN_ID_KEY: "r1"},
            created_at=now - timedelta(seconds=age_seconds),
        )
        with time_machine.travel(now, tick=False):
            status = lab_runs.run_cap_status([_todo(trigger_subscriptions=[watch])])
        assert status == expected

    async def test_run_status_reads_the_users_active_sandbox_run_todos(self) -> None:
        todos = AsyncMock()
        todos.find_active_by_user_and_trigger = AsyncMock(return_value=[])
        with patch(f"{LAB_RUNS}.todo_repository", new=todos):
            status = await lab_runs.lab_run_status(USER_ID)
        assert status == RunCapStatus(live=False, capped_todo_ids=[])
        todos.find_active_by_user_and_trigger.assert_awaited_once_with(
            USER_ID, lab_runs.SANDBOX_RUN_TRIGGER
        )

    async def test_subscribing_stores_a_fresh_watch_naming_the_run_folder(self) -> None:
        todo = _todo()
        stored = lab_runs.TriggerSubscription(
            trigger_name=lab_runs.SANDBOX_RUN_TRIGGER,
            action=SubscriptionAction.EXECUTE,
            resolution=lab_runs.SubscriptionResolution.ACCOUNT,
        )
        store = AsyncMock(return_value=(stored, True))
        with patch(f"{LAB_RUNS}.store_subscription", new=store):
            result = await lab_runs.subscribe_todo_to_run(todo, "r1")
        assert result is stored
        assert store.await_args.args[0] is todo
        assert store.await_args.kwargs == {
            "repaired": False,
            "activity": f"watching sandbox run r1 (run folder {run_dir('r1')})",
        }

    async def test_a_todo_gone_before_its_watch_is_stored_is_not_found(self) -> None:
        with (
            patch(f"{LAB_RUNS}.store_subscription", new=AsyncMock(return_value=None)),
            pytest.raises(AppError) as raised,
        ):
            await lab_runs.subscribe_todo_to_run(_todo(), "r1")
        error = raised.value
        assert (error.message, error.why, error.fix, error.status_code, error.code) == (
            "the todo could not be subscribed to its sandbox run",
            "todo t1 is gone",
            "check the tracked todo still exists, then launch the run again",
            404,
            "todo_subscription_not_stored",
        )
