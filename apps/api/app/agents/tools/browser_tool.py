"""The single executor-facing browser-automation tool.

The executor sees one tool, not the internals. The "do you want me to use a
browser?" confirmation is handled by the shared HIL system (``browser_task`` is
registered destructive). This file owns only the turn's half of a run: the
settings and URL gates, the identity read off the run's config, and where the
run's card frames go. Everything the run itself does lives in
``app/services/browser/job_runner.py``.
"""

from dataclasses import dataclass
from typing import Annotated, Any
import uuid

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from pydantic import BaseModel, ConfigDict

from app.config.settings import settings
from app.decorators import with_doc, with_rate_limiting
from app.models.chat_models import ConversationSource
from app.schemas.browser_job import BrowserJobRequest
from app.services.browser.job_runner import agent_result_message, execute_browser_job
from app.templates.docstrings.browser_tool_docs import BROWSER_TASK
from app.utils.url_safety import assert_safe_url_shape
from shared.py.wide_events import log


@dataclass(frozen=True)
class _RunParams:
    """The run's identity and provenance, read once from the tool's config."""

    user_id: str
    conversation_id: str
    stream_id: str | None
    root_request_id: str | None
    source_category: str | None
    conversation_source: ConversationSource | None


class _RunConfigurable(BaseModel):
    """The keys of the run's configurable this tool reads; the rest is the graph's."""

    model_config = ConfigDict(extra="ignore")

    user_id: str | None = None
    conversation_id: str | None = None
    thread_id: str | None = None
    stream_id: str | None = None
    root_request_id: str | None = None
    source_category: str | None = None
    conversation_source: str | None = None


def _run_params(config: RunnableConfig) -> _RunParams:
    configurable = _RunConfigurable.model_validate(config.get("configurable", {}))
    conv_source = ConversationSource.coerce(configurable.conversation_source)
    return _RunParams(
        user_id=configurable.user_id or "",
        # The USER-facing conversation, never the executor's derived thread_id
        # (executor_<conv>): a handoff is resolved by a chat reply arriving on the
        # comms conversation id, so a prefixed key would never match.
        conversation_id=configurable.conversation_id or configurable.thread_id or "",
        stream_id=configurable.stream_id,
        root_request_id=configurable.root_request_id,
        source_category=configurable.source_category,
        conversation_source=conv_source,
    )


def _job_request(params: _RunParams, task: str, start_url: str | None) -> BrowserJobRequest:
    return BrowserJobRequest(
        job_id=uuid.uuid4().hex,
        user_id=params.user_id,
        conversation_id=params.conversation_id,
        task=task,
        start_url=start_url,
        stream_id=params.stream_id,
        root_request_id=params.root_request_id,
        source_category=params.source_category,
        conversation_source=params.conversation_source,
    )


@tool
@with_rate_limiting("browser_task")
@with_doc(BROWSER_TASK)
async def browser_task(
    config: RunnableConfig,
    task: Annotated[str, "Clear, self-contained description of what to do in the browser."],
    start_url: Annotated[str | None, "Optional URL to open first."] = None,
) -> str:
    """Drive a browser task end to end: allocate a session, run the agent loop,
    and stream progress/result cards. Returns the outcome guidance message the
    executor surfaces to the user (never a fabricated success).
    """
    params = _run_params(config)
    log.set(browser={"operation": "task", "source_category": params.source_category})

    if not settings.BROWSER_USE_ENABLED:
        return "Browser automation is currently disabled."
    if start_url and not settings.BROWSER_HOST_ALLOW_PRIVATE_NETWORK:
        try:
            assert_safe_url_shape(start_url)
        except ValueError as exc:
            return f"I can't open {start_url}: {exc}. Only public http(s) sites are reachable."

    writer = get_stream_writer()

    async def publish(payload: dict[str, Any]) -> None:
        """The run still belongs to this turn, so its frames go straight onto the graph's stream."""
        writer(payload)

    result = await execute_browser_job(_job_request(params, task, start_url), publish=publish)
    return agent_result_message(result)
