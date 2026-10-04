"""Seed -> relay chain through a fake sandbox that really executes bash.

Seeds a run directly with the REAL seeder (mint_lab_hooks_token plus
build_seed_command output runs through a local bash, not a string match),
records the run id on the todo's references, then simulates the sandbox's
hook POST at the REAL record_lab_event service level with a faked todo
repository.

Service level, not the HTTP endpoint, deliberately: the endpoint needs full
app boot plus Redis budget counters; the token-ownership check it performs is
mirrored inline (body session must equal the token's run id). The mint,
fragment render, seed execution, hook parsing and tail filing are all real.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.models.todo_models import TodoDocument, TodoUpdate
from app.services.agent_lab import sandbox_setup
import app.services.agent_lab.lab_events as lab_events_mod
from app.services.agent_lab.lab_events import (
    LAB_TAIL_MARKER,
    parse_lab_event_body,
    record_lab_event,
)
from app.services.agent_lab.lab_runs import routing_ref, run_dir
from app.services.agent_lab.sandbox_setup import build_seed_command, mint_lab_hooks_token
from app.services.sandbox.execute_token import verify_execute_token
from tests.e2e._harness.fake_sandbox import FakeAsyncSandbox

pytestmark = pytest.mark.e2e

EVENTS_URL = "https://gaia.test/api/v1/lab/events"


class _FakeTodos:
    """In-memory todo store: the seeder writes refs here, the relay resolves them."""

    def __init__(self, todo: TodoDocument) -> None:
        self._todo = todo

    async def get(self, todo_id: str, user_id: str | None = None) -> TodoDocument | None:
        del user_id
        return self._todo if self._todo.id == todo_id else None

    async def add_references(
        self, todo_id: str, *, user_id: str, references: list[str]
    ) -> TodoDocument | None:
        del user_id
        if self._todo.id != todo_id:
            return None
        for ref in references:
            if ref not in self._todo.references:
                self._todo.references.append(ref)
        return self._todo

    async def find_by_reference(self, user_id: str, reference: str) -> TodoDocument | None:
        del user_id
        return self._todo if reference in self._todo.references else None

    async def replace_note_fields(
        self,
        todo_id: str,
        user_id: str,
        *,
        update: TodoUpdate,
        expected_updated_at: Any = None,
    ) -> TodoDocument | None:
        del user_id, expected_updated_at
        if self._todo.id != todo_id:
            return None
        if update.log_content is not None:
            self._todo.log_content = update.log_content
        return self._todo


def _lab_env(root: Any, run_id: str) -> dict[str, str]:
    lines = (root / ".gaia" / "lab" / run_id / ".gaia" / "lab-env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


async def test_seed_executes_then_hook_tail_is_filed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sandbox_setup.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", "test-secret-" + "x" * 32
    )
    monkeypatch.setattr(sandbox_setup.settings, "SANDBOX_LAB_EVENTS_CALLBACK_URL", EVENTS_URL)
    fake = FakeAsyncSandbox()
    todo = TodoDocument(id="t1", user_id="u-1", title="Fix billing")
    todos = _FakeTodos(todo)
    activity = AsyncMock(return_value=True)

    run_id = uuid4().hex
    cli_session_id = uuid4().hex
    token = mint_lab_hooks_token("u-1", run_id)
    seed = build_seed_command(sandbox_setup.lab_events_url(), token, run_id, run_dir(run_id))
    # Raises CommandExitException on a non-zero exit, so reaching the
    # assertions below proves the seed executed.
    await fake.commands.run(seed, timeout=300)
    await todos.add_references(
        "t1", user_id="u-1", references=[run_id, routing_ref(run_id, cli_session_id)]
    )

    bare = [r for r in todo.references if not r.startswith("lab:")]
    routing = [r for r in todo.references if r.startswith("lab:")]
    assert len(bare) == 1 and len(routing) == 1
    assert bare[0] == run_id
    assert routing[0].startswith(f"lab:{run_id}:")
    assert any(f"GAIA_LAB_RUN_ID={run_id}" in cmd for cmd in fake.commands.history)

    run_root = fake.root / ".gaia" / "lab" / run_id
    settings_text = (run_root / ".claude" / "settings.json").read_text()
    assert EVENTS_URL in settings_text
    assert "{{GAIA_LAB_" not in settings_text
    assert (run_root / ".gaia" / "claude-hooks.json").is_file()
    assert (run_root / ".opencode" / "plugins" / "gaia_lab_notify.js").is_file()
    env_path = run_root / ".gaia" / "lab-env"
    assert env_path.is_file()
    assert env_path.stat().st_mode & 0o077 == 0
    env = _lab_env(fake.root, run_id)
    assert env["GAIA_LAB_CALLBACK_URL"] == EVENTS_URL
    assert env["GAIA_LAB_TOKEN"]
    assert env["GAIA_LAB_SESSION_ID"] == run_id

    claims = verify_execute_token(env["GAIA_LAB_TOKEN"])
    assert claims.run_id == run_id
    assert claims.user_id == "u-1"
    assert claims.scoped_tool_names == []

    body = {
        "session_id": run_id,
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
    }
    event = parse_lab_event_body(body)
    assert event.kind == "pre_tool_use"
    assert event.session_id == claims.run_id

    with (
        patch.object(lab_events_mod, "is_paid", new=AsyncMock(return_value=True)),
        patch.object(lab_events_mod, "is_agent_lab_enabled", new=AsyncMock(return_value=True)),
        patch.object(lab_events_mod, "todo_repository", new=todos),
        patch.object(lab_events_mod, "record_activity", new=activity),
    ):
        receipt = await record_lab_event(
            event.session_id, user_id=claims.user_id, kind=event.kind, raw=event.raw
        )

    assert receipt.todo_id == "t1"
    assert receipt.id == run_id
    content = todo.log_content or ""
    assert LAB_TAIL_MARKER in content
    assert run_id in content
