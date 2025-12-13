"""E2B code execution tool with chart detection and streaming support."""

from typing import Annotated, Literal, Any

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from e2b_code_interpreter import Sandbox

from app.config.loggers import chat_logger as logger
from app.config.settings import settings
from app.templates.docstrings.code_exec_docs import CODE_EXECUTION_TOOL
from app.decorators import with_doc, with_rate_limiting
from app.utils.chart_utils import process_chart_results, validate_chart_data


@tool
@with_rate_limiting("code_execution")
@with_doc(CODE_EXECUTION_TOOL)
async def execute_code(
    config: RunnableConfig,
    language: Annotated[
        Literal["python", "javascript", "typescript", "r", "java", "bash"],
        "Programming language to use for code execution",
    ],
    code: Annotated[str, "The code to execute in the secure sandbox environment"],
    user_id: Annotated[str, "User ID for chart uploads"] = "anonymous",
) -> str:
    """Execute code safely in an isolated E2B sandbox with chart detection."""

    # Input validation
    if not code or not code.strip():
        return "Error: Code cannot be empty."

    if len(code) > 50000:  # 50KB limit
        return "Error: Code exceeds maximum length of 50,000 characters."

    # Validate language
    valid_languages = ["python", "javascript", "typescript", "r", "java", "bash"]
    if language.lower() not in valid_languages:
        return f"Error: Unsupported language '{language}'. Supported: {', '.join(valid_languages)}"

    if not hasattr(settings, "E2B_API_KEY") or not settings.E2B_API_KEY:
        return "Error: E2B API key not configured. Please set E2B_API_KEY in environment variables."

    writer = None
    try:
        writer = get_stream_writer()
        writer({"progress": f"Executing {language} code in secure E2B sandbox..."})

        # Send initial code data to frontend
        code_data: dict[str, Any] = {
            "code_data": {
                "language": language,
                "code": code,
                "output": None,
                "charts": None,
                "status": "executing",
            }
        }
        writer(code_data)

        # Create and execute in sandbox
        sbx = Sandbox()
        # Execute the code
        execution = sbx.run_code(code, language=language)

        charts, chart_errors = await process_chart_results(execution.results, user_id)

        logger.info(
            f"Charts processed: {len(charts) if charts else 0}, errors: {len(chart_errors) if chart_errors else 0}"
        )
        if charts:
            logger.info(f"Raw charts before validation: {charts}")

        # Validate chart data
        if charts:
            charts = validate_chart_data(charts)
            logger.info(f"Charts after validation: {len(charts) if charts else 0}")
            if charts:
                logger.info(f"Validated charts: {charts}")

        # Update code data with results
        code_data["code_data"]["output"] = {
            "stdout": "\n".join(execution.logs.stdout) if execution.logs.stdout else "",
            "stderr": "\n".join(execution.logs.stderr) if execution.logs.stderr else "",
            "results": (
                [str(result) for result in execution.results]
                if execution.results
                else []
            ),
            "error": str(execution.error) if execution.error else None,
        }

        if charts:
            code_data["code_data"]["charts"] = charts
            logger.info(f"Adding {len(charts)} charts to code_data")
        else:
            logger.info("No charts to add to code_data")

        # Include chart processing errors in output if any
        if chart_errors:
            current_output = code_data["code_data"]["output"]
            if isinstance(current_output, dict) and "stderr" in current_output:
                if current_output["stderr"]:
                    current_output["stderr"] += (
                        "\n\nChart Processing Warnings:\n" + "\n".join(chart_errors)
                    )
                else:
                    current_output["stderr"] = (
                        "Chart Processing Warnings:\n" + "\n".join(chart_errors)
                    )

        code_data["code_data"]["status"] = "completed"
        logger.info(f"Streaming final code_data: {code_data}")
        writer(code_data)

        # Format output for return
        output_parts = []

        if execution.logs.stdout:
            output_parts.append(f"Output:\n{chr(10).join(execution.logs.stdout)}")

        if execution.results:
            results_text = "\n".join(str(result) for result in execution.results)
            output_parts.append(f"Results:\n{results_text}")

        if execution.logs.stderr:
            output_parts.append(f"Errors:\n{chr(10).join(execution.logs.stderr)}")

        if execution.error:
            output_parts.append(f"Execution Error: {execution.error}")

        if charts:
            output_parts.append(f"Generated {len(charts)} chart(s)")

        if chart_errors:
            output_parts.append(
                f"Chart processing warnings: {len(chart_errors)} issue(s)"
            )

        return (
            "\n\n".join(output_parts)
            if output_parts
            else "Code executed successfully (no output)"
        )

    except Exception as e:
        error_msg = f"Error executing code: {str(e)}"
        logger.error(error_msg)

        # Send error state to frontend
        if writer:
            try:
                writer(
                    {
                        "code_data": {
                            "language": language,
                            "code": code,
                            "output": {
                                "stdout": "",
                                "stderr": str(e),
                                "results": [],
                                "error": str(e),
                            },
                            "charts": None,
                            "status": "error",
                        }
                    }
                )
            except Exception as streaming_error:
                # Log streaming errors but don't mask the original error
                logger.error(
                    f"Failed to send error state to frontend: {str(streaming_error)}",
                    exc_info=True,
                )

        return error_msg
