import asyncio
from typing import Any
from uuid import UUID

from posthog import Posthog
from posthog.ai.langchain import CallbackHandler as PostHogCallbackHandler

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider

# Raised at a run's yield point when the client closes the chat stream or the
# ainvoke_llm wall-clock ceiling expires. Both are BaseException lifecycle
# signals, not failures — the codebase already treats them as a clean exit
# (see libs/shared/py/wide_events.py, which records outcome="cancelled").
_STREAM_CANCELLATION_EXCEPTIONS = (asyncio.CancelledError, GeneratorExit)


class StreamCancellationSafeCallbackHandler(PostHogCallbackHandler):
    """PostHog LangChain callback that drops stream-cancellation lifecycle exceptions.

    The base handler reports every ``on_*_error`` to error tracking, so a normal
    stream cancellation reached error tracking as a CancelledError or GeneratorExit
    crash — duplicated at each nested runnable level. Filter those two lifecycle
    types out; genuine LLM failures still report unchanged.
    """

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,  # noqa: ANN401 -- LangChain BaseCallbackHandler contract
    ) -> None:
        if isinstance(error, _STREAM_CANCELLATION_EXCEPTIONS):
            return
        super().on_llm_error(error, run_id=run_id, parent_run_id=parent_run_id, **kwargs)

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,  # noqa: ANN401 -- LangChain BaseCallbackHandler contract
    ) -> None:
        if isinstance(error, _STREAM_CANCELLATION_EXCEPTIONS):
            return
        super().on_chain_error(error, run_id=run_id, parent_run_id=parent_run_id, **kwargs)

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,  # noqa: ANN401 -- LangChain BaseCallbackHandler contract
    ) -> None:
        if isinstance(error, _STREAM_CANCELLATION_EXCEPTIONS):
            return
        super().on_tool_error(error, run_id=run_id, parent_run_id=parent_run_id, **kwargs)

    def on_retriever_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,  # noqa: ANN401 -- LangChain BaseCallbackHandler contract
    ) -> None:
        if isinstance(error, _STREAM_CANCELLATION_EXCEPTIONS):
            return
        super().on_retriever_error(error, run_id=run_id, parent_run_id=parent_run_id, **kwargs)


@lazy_provider(
    name="posthog",
    required_keys=[
        settings.POSTHOG_PROJECT_TOKEN,
        settings.POSTHOG_HOST,
    ],
    auto_initialize=False,
    is_global_context=False,
    strategy=MissingKeyStrategy.SILENT,
)
def init_posthog() -> Posthog:
    """Initialize the shared PostHog client from environment-backed settings."""
    return Posthog(
        settings.POSTHOG_PROJECT_TOKEN,
        host=settings.POSTHOG_HOST,
        enable_exception_autocapture=True,
    )
