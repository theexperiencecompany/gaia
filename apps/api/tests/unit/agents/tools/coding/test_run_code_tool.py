"""run_code — sandbox seeding, token injection, and the unconfigured refusal."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.coding import run_code_tool
from app.agents.tools.coding.run_code_tool import run_code

MODULE = "app.agents.tools.coding.run_code_tool"
CONFIG: dict[str, Any] = {"configurable": {"user_id": "u1", "stream_id": "s1"}}


class _FakeSandbox:
    def __init__(self) -> None:
        self.files = SimpleNamespace(write=AsyncMock())
        self.commands = SimpleNamespace(
            run=AsyncMock(return_value=SimpleNamespace(exit_code=0, stdout="TOTAL=42\n", stderr=""))
        )


def _acquire(sbx: _FakeSandbox) -> MagicMock:
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=sbx)
    manager.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=manager)


@pytest.mark.unit
class TestRunCode:
    async def test_unconfigured_deployment_refuses_loudly(self) -> None:
        with (
            patch.object(run_code_tool.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", None),
            patch(f"{MODULE}.acquire_sandbox") as acquire,
        ):
            result = await run_code.ainvoke({"script": "print(1)"}, config=CONFIG)
        assert "not configured" in result
        acquire.assert_not_called()

    async def test_seeds_client_and_runs_with_token_env(self) -> None:
        sbx = _FakeSandbox()
        with (
            patch.object(run_code_tool.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", "s" * 32),
            patch.object(
                run_code_tool.settings,
                "SANDBOX_EXECUTE_CALLBACK_URL",
                "https://api.test/api/v1/sandbox/execute",
            ),
            patch(f"{MODULE}.mint_execute_token", return_value="tok-1") as mint,
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
        ):
            result = await run_code.ainvoke(
                {"script": "from gaia import execute\nprint('hi')"}, config=CONFIG
            )

        written_paths = [call.args[0] for call in sbx.files.write.await_args_list]
        assert any(path.endswith("/gaia.py") for path in written_paths)
        assert any(path.endswith("/script.py") for path in written_paths)

        run_kwargs = sbx.commands.run.await_args.kwargs
        assert run_kwargs["envs"]["GAIA_EXECUTE_TOKEN"] == "tok-1"
        assert run_kwargs["envs"]["GAIA_EXECUTE_URL"].endswith("/sandbox/execute")

        mint_kwargs = mint.call_args.kwargs
        assert mint.call_args.args[0] == "u1"
        assert mint_kwargs["stream_id"] == "s1"

        payload = json.loads(result)
        assert payload["exit_code"] == 0
        assert "TOTAL=42" in payload["stdout"]

    async def test_script_failure_surfaces_stderr(self) -> None:
        sbx = _FakeSandbox()
        sbx.commands.run = AsyncMock(
            return_value=SimpleNamespace(exit_code=1, stdout="", stderr="Traceback: boom")
        )
        with (
            patch.object(run_code_tool.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", "s" * 32),
            patch.object(
                run_code_tool.settings,
                "SANDBOX_EXECUTE_CALLBACK_URL",
                "https://api.test/api/v1/sandbox/execute",
            ),
            patch(f"{MODULE}.mint_execute_token", return_value="tok-1"),
            patch(f"{MODULE}.acquire_sandbox", new=_acquire(sbx)),
        ):
            result = await run_code.ainvoke({"script": "raise SystemExit(1)"}, config=CONFIG)
        payload = json.loads(result)
        assert payload["exit_code"] == 1
        assert "boom" in payload["stderr"]
