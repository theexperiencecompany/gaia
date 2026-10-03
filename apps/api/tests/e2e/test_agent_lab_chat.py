"""Agent-lab chat tools through the real executor graph (fake LLM, fake sandbox).

Drives lab_start / lab_message / lab_stop as the model would call them and
asserts on what the graph did: the seed command that reached the sandbox, the
run + session ids recorded on the todo, inbox delivery, stop behavior, the
todo-linkage refusal, and the AGENT_LAB flag hiding the tools from retrieval
while the bodies refuse when called directly.

The sandbox, the todo repository, the flag and the token mint are doubles; the
graph, the tool bodies, the registry and build_seed_command are real.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from e2b import CommandExitException
import pytest

import app.agents.tools.agent_lab_tools as lab_tools
from app.constants.todos import TodoActivityEvent
from app.models.todo_models import TodoDocument
from tests.e2e._harness.graph_run import (
    SELECT_NODE,
    call,
    executor_graph,
    run_graph,
)

pytestmark = pytest.mark.e2e

LAB_START_ARGS = {"task": "Probe the billing page", "active_todo_id": "t1"}
EVENTS_URL = "https://gaia.test/api/v1/lab/events"


def _todo(**overrides: Any) -> TodoDocument:
    fields: dict[str, Any] = {"id": "t1", "user_id": "u-1", "title": "Fix billing"}
    fields.update(overrides)
    return TodoDocument(**fields)


class _AcquireCM:
    """An async context manager yielding the fake sandbox (mirrors acquire_sandbox use)."""

    def __init__(self, sbx: Any) -> None:
        self._sbx = sbx

    async def __aenter__(self) -> Any:
        return self._sbx

    async def __aexit__(self, *args: Any) -> bool:
        return False


def _sandbox() -> MagicMock:
    sbx = MagicMock()
    sbx.commands.run = AsyncMock(
        return_value=SimpleNamespace(exit_code=0, stdout="GAIA_LAB_RUN_ID=abc", stderr="")
    )
    sbx.files.make_dir = AsyncMock()
    sbx.files.write = AsyncMock()
    return sbx


def _patch_lab(
    sbx: MagicMock,
    todo: TodoDocument,
    *,
    flag: bool = True,
    active_todo_id: str | None = None,
) -> dict[str, Any]:
    """Patch every seam of the lab tools; returns the mocks for assertions."""
    repo = MagicMock()
    repo.get = AsyncMock(return_value=todo)
    repo.add_references = AsyncMock(return_value=todo)
    activity = AsyncMock(return_value=True)
    patches = [
        patch.object(lab_tools, "is_agent_lab_enabled", new=AsyncMock(return_value=flag)),
        patch.object(lab_tools, "todo_repository", new=repo),
        patch.object(lab_tools, "acquire_sandbox", new=MagicMock(return_value=_AcquireCM(sbx))),
        patch.object(lab_tools, "record_activity", new=activity),
        patch.object(lab_tools, "mint_lab_hooks_token", new=MagicMock(return_value="tok-test")),
        patch.object(lab_tools, "lab_events_url", new=MagicMock(return_value=EVENTS_URL)),
        patch(
            "app.agents.tools.core.retrieval.is_agent_lab_enabled",
            new=AsyncMock(return_value=flag),
        ),
    ]
    if active_todo_id is not None:
        patches.append(
            patch.object(
                lab_tools,
                "agent_configurable",
                new=MagicMock(return_value={"active_todo_id": active_todo_id}),
            )
        )
    return {"repo": repo, "activity": activity, "patches": patches}


def _references_of(repo: MagicMock) -> list[str]:
    return list(repo.add_references.await_args.kwargs["references"])


class _RunWith:
    """Enter patches, drive one scripted executor turn, hand back the GraphRun."""

    def __init__(self, patches: list[Any], script: list[Any], **kwargs: Any) -> None:
        self._patches = patches
        self._script = script
        self._kwargs = kwargs

    async def __aenter__(self):
        from contextlib import ExitStack

        self._exit = ExitStack()
        for p in self._patches:
            self._exit.enter_context(p)
        self._graph_cm = executor_graph(self._script)
        graph = await self._graph_cm.__aenter__()
        run = await run_graph(graph, "lab work please", thread_id=f"lab-{uuid4()}", **self._kwargs)
        return run

    async def __aexit__(self, *args: Any) -> bool:
        await self._graph_cm.__aexit__(*args)
        self._exit.close()
        return False


class TestLabStart:
    async def test_start_seeds_the_run_workdir_and_records_both_ids(self):
        """The seed reaches the sandbox with the per-run workdir; the todo gets the bare run id (receiver shape) plus the lab: routing entry."""
        sbx = _sandbox()
        todo = _todo(references=[])
        ctx = _patch_lab(sbx, todo)
        async with _RunWith(
            ctx["patches"], [call("lab_start", dict(LAB_START_ARGS)), "Started."]
        ) as run:
            pass

        assert run.ran("lab_start")
        seed_cmd = sbx.commands.run.await_args.args[0]
        assert "/workspace/.gaia/lab/" in seed_cmd
        assert ".claude/settings.json" in seed_cmd
        refs = _references_of(ctx["repo"])
        assert len(refs) == 2
        run_id, routing = refs
        assert routing == f"lab:{run_id}:{routing.split(':')[2]}"
        assert len(run_id) == 32
        result = run.result_for("lab_start") or ""
        assert "Fix billing" in result
        ctx["activity"].assert_awaited_once()
        event = ctx["activity"].await_args.args[2]
        assert event is TodoActivityEvent.RUN_STARTED

    async def test_start_refuses_without_a_tracked_todo_and_touches_nothing(self):
        """No todo id anywhere: the run never reaches the sandbox or the repository."""
        sbx = _sandbox()
        ctx = _patch_lab(sbx, _todo())
        async with _RunWith(
            ctx["patches"], [call("lab_start", {"task": "orphan work"}), "ok"]
        ) as run:
            pass

        result = run.result_for("lab_start") or ""
        assert "tracked todo" in result
        sbx.commands.run.assert_not_awaited()
        ctx["repo"].add_references.assert_not_awaited()
        ctx["repo"].get.assert_not_awaited()

    async def test_start_rejects_a_missing_or_foreign_todo(self):
        sbx = _sandbox()
        ctx = _patch_lab(sbx, _todo())
        ctx["repo"].get = AsyncMock(return_value=None)
        async with _RunWith(ctx["patches"], [call("lab_start", dict(LAB_START_ARGS)), "ok"]) as run:
            pass

        result = run.result_for("lab_start") or ""
        assert "does not exist" in result
        sbx.commands.run.assert_not_awaited()


class TestLabMessage:
    def _todo_with_run(self) -> tuple[str, str, TodoDocument]:
        run_id = uuid4().hex
        cli_session_id = uuid4().hex
        return run_id, cli_session_id, _todo(references=[f"lab:{run_id}:{cli_session_id}"])

    async def test_message_lands_in_the_run_inbox_and_is_recorded(self):
        run_id, cli_session_id, todo = self._todo_with_run()
        sbx = _sandbox()
        ctx = _patch_lab(sbx, todo, active_todo_id="t1")
        script = [call("lab_message", {"text": "use the staging key"}), "Relayed."]
        async with _RunWith(ctx["patches"], script) as run:
            pass

        assert run.ran("lab_message")
        inbox_path = sbx.files.write.await_args.args[0]
        assert inbox_path.startswith(f"/workspace/.gaia/lab/{run_id}/.gaia/inbox/")
        assert sbx.files.write.await_args.args[1].startswith("use the staging key")
        ctx["activity"].assert_awaited_once()
        assert ctx["activity"].await_args.args[2] is TodoActivityEvent.LAB_MESSAGE_RELAYED
        result = run.result_for("lab_message") or ""
        assert cli_session_id in result

    async def test_message_without_a_run_says_so(self):
        sbx = _sandbox()
        ctx = _patch_lab(sbx, _todo(references=["some-unrelated-todo-id"]), active_todo_id="t1")
        async with _RunWith(ctx["patches"], [call("lab_message", {"text": "hi"}), "ok"]) as run:
            pass

        assert "no lab run yet" in (run.result_for("lab_message") or "")
        sbx.files.write.assert_not_awaited()

    async def test_message_prefers_the_latest_run(self):
        """Noise entries (related-todo refs, a malformed lab: entry, an older run) never misroute."""
        old_run, old_cli = uuid4().hex, uuid4().hex
        new_run, new_cli = uuid4().hex, uuid4().hex
        todo = _todo(
            references=[
                "deadbeefdeadbeefdeadbeef",
                "lab:malformed",
                f"lab:{old_run}:{old_cli}",
                new_run,
                f"lab:{new_run}:{new_cli}",
            ]
        )
        sbx = _sandbox()
        ctx = _patch_lab(sbx, todo, active_todo_id="t1")
        async with _RunWith(ctx["patches"], [call("lab_message", {"text": "go on"}), "ok"]) as run:
            pass

        inbox_path = sbx.files.write.await_args.args[0]
        assert inbox_path.startswith(f"/workspace/.gaia/lab/{new_run}/.gaia/inbox/")
        assert new_cli in (run.result_for("lab_message") or "")


class TestLabStop:
    async def test_stop_signals_the_run_and_records_it(self):
        run_id, cli_session_id = uuid4().hex, uuid4().hex
        todo = _todo(references=[run_id, f"lab:{run_id}:{cli_session_id}"])
        sbx = _sandbox()
        ctx = _patch_lab(sbx, todo, active_todo_id="t1")
        async with _RunWith(ctx["patches"], [call("lab_stop", {}), "Stopped."]) as run:
            pass

        assert run.ran("lab_stop")
        kill_cmd = sbx.commands.run.await_args.args[0]
        assert "pkill" in kill_cmd and cli_session_id in kill_cmd
        assert run_id not in kill_cmd
        ctx["activity"].assert_awaited_once()
        assert ctx["activity"].await_args.args[2] is TodoActivityEvent.RUN_FINISHED
        assert "has stopped" in (run.result_for("lab_stop") or "")

    async def test_stop_reports_an_already_dead_run_without_failing(self):
        """Pkill exit 1 (no process matched) is 'already stopped', not an error."""
        run_id, cli_session_id = uuid4().hex, uuid4().hex
        todo = _todo(references=[f"lab:{run_id}:{cli_session_id}"])
        sbx = _sandbox()
        sbx.commands.run = AsyncMock(
            side_effect=CommandExitException("", "", 1, None),
        )
        ctx = _patch_lab(sbx, todo, active_todo_id="t1")
        async with _RunWith(ctx["patches"], [call("lab_stop", {}), "ok"]) as run:
            pass

        assert "no live process" in (run.result_for("lab_stop") or "")
        ctx["activity"].assert_awaited_once()


def _retrieve(*names: str, retrieve_id: str = "r1") -> dict[str, Any]:
    return call(
        "retrieve_tools", {"query": " ".join(names), "exact_tool_names": list(names)}, retrieve_id
    )


class TestFlagGating:
    async def test_flag_off_hides_lab_tools_from_retrieval_but_direct_calls_refuse(self):
        """Listing gate: exact-name binding reports unknown; the statically bound body still refuses with the disabled message."""
        sbx = _sandbox()
        ctx = _patch_lab(sbx, _todo(), flag=False)
        script = [_retrieve("lab_start"), call("lab_start", dict(LAB_START_ARGS)), "ok"]
        async with _RunWith(ctx["patches"], script) as run:
            pass

        assert run.results_from(SELECT_NODE) == [
            "Not found, nothing bound: lab_start. Do not retry these names; run retrieve_tools(query=...) to find what actually exists."
        ]
        # Statically bound, so a direct call still executes — and refuses at the body.
        assert run.ran("lab_start")
        assert "not enabled" in (run.result_for("lab_start") or "")
        sbx.commands.run.assert_not_awaited()

    async def test_flag_on_binds_lab_start_by_exact_name(self):
        sbx = _sandbox()
        ctx = _patch_lab(sbx, _todo(), flag=True)
        async with _RunWith(ctx["patches"], [_retrieve("lab_start"), "ok"]) as run:
            pass

        assert run.bound_tools() == ["lab_start"]

    async def test_flag_off_blocks_message_and_stop_without_touching_the_sandbox(self):
        sbx = _sandbox()
        run_id, cli_session_id = uuid4().hex, uuid4().hex
        todo = _todo(references=[f"lab:{run_id}:{cli_session_id}"])
        ctx = _patch_lab(sbx, todo, flag=False, active_todo_id="t1")
        script = [call("lab_message", {"text": "hi"}), call("lab_stop", {}, call_id="c2"), "ok"]
        async with _RunWith(ctx["patches"], script) as run:
            pass

        assert "not enabled" in (run.result_for("lab_message") or "")
        assert "not enabled" in (run.result_for("lab_stop") or "")
        sbx.commands.run.assert_not_awaited()
        sbx.files.write.assert_not_awaited()
