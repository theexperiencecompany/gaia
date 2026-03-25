"""Unit tests for app.agents.tools.code_exec_tool."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.code_exec_tool"


def _make_config(user_id: str = FAKE_USER_ID) -> Dict[str, Any]:
    """Return a minimal RunnableConfig-like dict."""
    return {"metadata": {"user_id": user_id}}


def _writer_mock() -> MagicMock:
    return MagicMock()


def _make_execution_result(
    stdout: list[str] | None = None,
    stderr: list[str] | None = None,
    results: list[Any] | None = None,
    error: Any = None,
) -> MagicMock:
    """Create a mock E2B execution result."""
    mock = MagicMock()
    mock.logs = MagicMock()
    mock.logs.stdout = stdout or []
    mock.logs.stderr = stderr or []
    mock.results = results or []
    mock.error = error
    return mock


def _make_settings_mock(has_e2b_key: bool = True) -> MagicMock:
    """Create a settings mock with optional E2B key."""
    settings = MagicMock()
    settings.E2B_API_KEY = "test-e2b-key" if has_e2b_key else ""
    return settings


# ---------------------------------------------------------------------------
# Tests: execute_code
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteCode:
    """Tests for the execute_code tool."""

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.validate_chart_data")
    @patch(f"{MODULE}.process_chart_results", new_callable=AsyncMock)
    @patch(f"{MODULE}.Sandbox")
    @patch(f"{MODULE}.settings")
    async def test_happy_path_python(
        self,
        mock_settings: MagicMock,
        mock_sandbox_cls: MagicMock,
        mock_process_charts: AsyncMock,
        mock_validate_charts: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Successfully executes Python code with stdout output."""
        mock_settings.E2B_API_KEY = "test-key"
        writer = _writer_mock()
        mock_writer_factory.return_value = writer

        execution = _make_execution_result(stdout=["Hello, World!"])
        mock_sandbox = MagicMock()
        mock_sandbox.run_code.return_value = execution
        mock_sandbox_cls.return_value = mock_sandbox

        mock_process_charts.return_value = ([], [])
        mock_validate_charts.return_value = []

        from app.agents.tools.code_exec_tool import execute_code

        result = await execute_code.coroutine(
            config=_make_config(),
            language="python",
            code="print('Hello, World!')",
        )

        assert "Hello, World!" in result
        mock_sandbox.run_code.assert_called_once_with(
            "print('Hello, World!')", language="python"
        )

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.settings")
    async def test_empty_code_returns_error(
        self,
        mock_settings: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Empty code string returns validation error."""
        mock_settings.E2B_API_KEY = "test-key"
        mock_writer_factory.return_value = _writer_mock()

        from app.agents.tools.code_exec_tool import execute_code

        result = await execute_code.coroutine(
            config=_make_config(),
            language="python",
            code="",
        )

        assert "Error: Code cannot be empty" in result

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.settings")
    async def test_whitespace_only_code_returns_error(
        self,
        mock_settings: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Whitespace-only code is rejected."""
        mock_settings.E2B_API_KEY = "test-key"
        mock_writer_factory.return_value = _writer_mock()

        from app.agents.tools.code_exec_tool import execute_code

        result = await execute_code.coroutine(
            config=_make_config(),
            language="python",
            code="   \n  ",
        )

        assert "Error: Code cannot be empty" in result

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.settings")
    async def test_code_too_long_returns_error(
        self,
        mock_settings: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Code exceeding 50K characters is rejected."""
        mock_settings.E2B_API_KEY = "test-key"
        mock_writer_factory.return_value = _writer_mock()

        from app.agents.tools.code_exec_tool import execute_code

        result = await execute_code.coroutine(
            config=_make_config(),
            language="python",
            code="x" * 50001,
        )

        assert "Error: Code exceeds maximum length" in result

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.settings")
    async def test_missing_e2b_key(
        self,
        mock_settings: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Missing E2B API key returns configuration error."""
        mock_settings.E2B_API_KEY = ""
        mock_writer_factory.return_value = _writer_mock()

        from app.agents.tools.code_exec_tool import execute_code

        result = await execute_code.coroutine(
            config=_make_config(),
            language="python",
            code="print('hello')",
        )

        assert "E2B API key not configured" in result

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.validate_chart_data")
    @patch(f"{MODULE}.process_chart_results", new_callable=AsyncMock)
    @patch(f"{MODULE}.Sandbox")
    @patch(f"{MODULE}.settings")
    async def test_execution_with_stderr(
        self,
        mock_settings: MagicMock,
        mock_sandbox_cls: MagicMock,
        mock_process_charts: AsyncMock,
        mock_validate_charts: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Stderr is included in output."""
        mock_settings.E2B_API_KEY = "test-key"
        writer = _writer_mock()
        mock_writer_factory.return_value = writer

        execution = _make_execution_result(stderr=["Warning: deprecated"])
        mock_sandbox = MagicMock()
        mock_sandbox.run_code.return_value = execution
        mock_sandbox_cls.return_value = mock_sandbox
        mock_process_charts.return_value = ([], [])

        from app.agents.tools.code_exec_tool import execute_code

        result = await execute_code.coroutine(
            config=_make_config(),
            language="python",
            code="import warnings",
        )

        assert "Warning: deprecated" in result

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.validate_chart_data")
    @patch(f"{MODULE}.process_chart_results", new_callable=AsyncMock)
    @patch(f"{MODULE}.Sandbox")
    @patch(f"{MODULE}.settings")
    async def test_execution_with_error(
        self,
        mock_settings: MagicMock,
        mock_sandbox_cls: MagicMock,
        mock_process_charts: AsyncMock,
        mock_validate_charts: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Execution error is reported in output."""
        mock_settings.E2B_API_KEY = "test-key"
        writer = _writer_mock()
        mock_writer_factory.return_value = writer

        execution = _make_execution_result(error="NameError: name 'x' is not defined")
        mock_sandbox = MagicMock()
        mock_sandbox.run_code.return_value = execution
        mock_sandbox_cls.return_value = mock_sandbox
        mock_process_charts.return_value = ([], [])

        from app.agents.tools.code_exec_tool import execute_code

        result = await execute_code.coroutine(
            config=_make_config(),
            language="python",
            code="print(x)",
        )

        assert "NameError" in result

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.validate_chart_data")
    @patch(f"{MODULE}.process_chart_results", new_callable=AsyncMock)
    @patch(f"{MODULE}.Sandbox")
    @patch(f"{MODULE}.settings")
    async def test_with_charts(
        self,
        mock_settings: MagicMock,
        mock_sandbox_cls: MagicMock,
        mock_process_charts: AsyncMock,
        mock_validate_charts: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Charts are processed and included in output."""
        mock_settings.E2B_API_KEY = "test-key"
        writer = _writer_mock()
        mock_writer_factory.return_value = writer

        execution = _make_execution_result(stdout=["Plot created"])
        mock_sandbox = MagicMock()
        mock_sandbox.run_code.return_value = execution
        mock_sandbox_cls.return_value = mock_sandbox

        charts = [{"type": "bar", "url": "https://charts.example.com/bar.png"}]
        mock_process_charts.return_value = (charts, [])
        mock_validate_charts.return_value = charts

        from app.agents.tools.code_exec_tool import execute_code

        result = await execute_code.coroutine(
            config=_make_config(),
            language="python",
            code="import matplotlib",
            user_id="user-1",
        )

        assert "Generated 1 chart(s)" in result

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.Sandbox")
    @patch(f"{MODULE}.settings")
    async def test_sandbox_exception_returns_error(
        self,
        mock_settings: MagicMock,
        mock_sandbox_cls: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Sandbox creation failure returns error string."""
        mock_settings.E2B_API_KEY = "test-key"
        writer = _writer_mock()
        mock_writer_factory.return_value = writer
        mock_sandbox_cls.side_effect = Exception("Sandbox creation timeout")

        from app.agents.tools.code_exec_tool import execute_code

        result = await execute_code.coroutine(
            config=_make_config(),
            language="python",
            code="print('hi')",
        )

        assert "Error executing code" in result
        assert "Sandbox creation timeout" in result

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.validate_chart_data")
    @patch(f"{MODULE}.process_chart_results", new_callable=AsyncMock)
    @patch(f"{MODULE}.Sandbox")
    @patch(f"{MODULE}.settings")
    async def test_no_output_returns_success_message(
        self,
        mock_settings: MagicMock,
        mock_sandbox_cls: MagicMock,
        mock_process_charts: AsyncMock,
        mock_validate_charts: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Code with no output returns success fallback message."""
        mock_settings.E2B_API_KEY = "test-key"
        mock_writer_factory.return_value = _writer_mock()

        execution = _make_execution_result()
        mock_sandbox = MagicMock()
        mock_sandbox.run_code.return_value = execution
        mock_sandbox_cls.return_value = mock_sandbox
        mock_process_charts.return_value = ([], [])

        from app.agents.tools.code_exec_tool import execute_code

        result = await execute_code.coroutine(
            config=_make_config(),
            language="python",
            code="x = 1",
        )

        assert result == "Code executed successfully (no output)"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.validate_chart_data")
    @patch(f"{MODULE}.process_chart_results", new_callable=AsyncMock)
    @patch(f"{MODULE}.Sandbox")
    @patch(f"{MODULE}.settings")
    async def test_streams_code_data_to_writer(
        self,
        mock_settings: MagicMock,
        mock_sandbox_cls: MagicMock,
        mock_process_charts: AsyncMock,
        mock_validate_charts: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Verifies code_data events are streamed to writer."""
        mock_settings.E2B_API_KEY = "test-key"
        writer = _writer_mock()
        mock_writer_factory.return_value = writer

        execution = _make_execution_result(stdout=["42"])
        mock_sandbox = MagicMock()
        mock_sandbox.run_code.return_value = execution
        mock_sandbox_cls.return_value = mock_sandbox
        mock_process_charts.return_value = ([], [])

        from app.agents.tools.code_exec_tool import execute_code

        await execute_code.coroutine(
            config=_make_config(),
            language="python",
            code="print(42)",
        )

        code_calls = [c for c in writer.call_args_list if "code_data" in c[0][0]]
        # Should have initial + final code_data calls
        assert len(code_calls) >= 2
        # The last code_data call should have status "completed"
        last_code = code_calls[-1][0][0]["code_data"]
        assert last_code["status"] == "completed"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.validate_chart_data")
    @patch(f"{MODULE}.process_chart_results", new_callable=AsyncMock)
    @patch(f"{MODULE}.Sandbox")
    @patch(f"{MODULE}.settings")
    async def test_chart_processing_errors_appended_to_stderr(
        self,
        mock_settings: MagicMock,
        mock_sandbox_cls: MagicMock,
        mock_process_charts: AsyncMock,
        mock_validate_charts: MagicMock,
        mock_writer_factory: MagicMock,
    ) -> None:
        """Chart processing errors are appended to stderr in output."""
        mock_settings.E2B_API_KEY = "test-key"
        writer = _writer_mock()
        mock_writer_factory.return_value = writer

        execution = _make_execution_result(stdout=["done"])
        mock_sandbox = MagicMock()
        mock_sandbox.run_code.return_value = execution
        mock_sandbox_cls.return_value = mock_sandbox

        mock_process_charts.return_value = ([], ["Chart upload failed"])
        mock_validate_charts.return_value = []

        from app.agents.tools.code_exec_tool import execute_code

        result = await execute_code.coroutine(
            config=_make_config(),
            language="python",
            code="import matplotlib",
        )

        assert "chart processing warnings" in result.lower()
