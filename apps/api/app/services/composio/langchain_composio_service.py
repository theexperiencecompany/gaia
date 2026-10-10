"""ComposioLangChain class definition."""

import asyncio
from dataclasses import dataclass
from inspect import Parameter, Signature
import types
import typing as t

from composio.core.models.tools import ToolExecutionResponse
from composio.core.provider import AgenticProvider, AgenticProviderExecuteFn
from composio.core.provider.base import BaseProviderConfig
from composio.types import Tool
from composio.utils.pydantic import parse_pydantic_error
from composio.utils.shared import (
    get_signature_format_from_schema_params,
    json_schema_to_model,
)
import composio_client
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import StructuredTool as BaseStructuredTool
import pydantic

from app.config.oauth_config import get_integration_by_toolkit
from app.constants.log_tags import LogTag
from app.services.integrations.integration_expiry import ExpiryOptions, expire_user_integration
from app.utils.integration_checker import request_integration_connection
from shared.py.wide_events import log, log_context

_python_reserved = {"for", "async", "from", "import", "as", "pass", "continue"}

# Composio's tool-execute failure for a missing/expired/revoked connected
# account: error code 1810, name ActionExecute_ConnectedAccountNotFound. It
# surfaces as a raised NotFoundError (404) or a non-raising result, so both gate on this one marker set.
_DEAD_ACCOUNT_ERROR_CODE = "1810"
_DEAD_ACCOUNT_ERROR_NAME = "actionexecute_connectedaccountnotfound"
_DEAD_ACCOUNT_MESSAGE_MARKERS = (
    _DEAD_ACCOUNT_ERROR_CODE,
    _DEAD_ACCOUNT_ERROR_NAME,
    "no active connected account",
    "no connected account",
)

# How long the tool wrapper waits on the main loop for the expiry write plus the
# connect prompt. A timeout only abandons the wait — the coroutine keeps running
# on the loop, so the expiry still lands; the agent just gets the raw error.
_RECONNECT_PROMPT_TIMEOUT_S = 10.0


class _JsonSchema(t.TypedDict, total=False):
    """The JSON-schema keys this module reads; every other key rides along untouched."""

    type: object
    properties: dict[str, "_JsonSchema"]


@dataclass(frozen=True)
class _RenamedKeyword:
    """A schema property renamed off a Python keyword, with the renames inside it."""

    original: str
    nested: dict[str, "_RenamedKeyword"]


class _ComposioErrorBody(t.TypedDict, total=False):
    error: object


class _ComposioErrorDetail(t.TypedDict, total=False):
    error_code: object
    code: object
    name: object
    type: object


class _ToolCallTransport(t.TypedDict, total=False):
    """The one key the wrapper reads off a tool call's kwargs; the rest are tool arguments."""

    __runnable_config__: object


class _RunMetadataView(t.TypedDict, total=False):
    user_id: str | None


def _running_loop_or_none() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _message_mentions_dead_account(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _DEAD_ACCOUNT_MESSAGE_MARKERS)


def _is_dead_account_error(error: composio_client.NotFoundError) -> bool:
    """Confirm a Composio 404 is the dead-connected-account failure, not some other 404.

    Prefers the structured error body, because a false positive here marks a
    healthy integration expired; falls back to the message, which carries the
    same code and name.
    """
    body = error.body
    if isinstance(body, dict):
        error_body: _ComposioErrorBody = t.cast(_ComposioErrorBody, body)
        nested = error_body.get("error")
        raw_detail = nested if isinstance(nested, dict) else body
        if isinstance(raw_detail, dict):
            detail: _ComposioErrorDetail = t.cast(_ComposioErrorDetail, raw_detail)
            code = detail.get("error_code", detail.get("code"))
            name = detail.get("name", detail.get("type"))
            if str(code) == _DEAD_ACCOUNT_ERROR_CODE:
                return True
            if isinstance(name, str) and name.lower() == _DEAD_ACCOUNT_ERROR_NAME:
                return True
    return _message_mentions_dead_account(str(error))


async def _expire_with_log_boundary(user_id: str, integration_id: str, reason: str) -> None:
    """Run the expiry transition under its own wide-event boundary.

    The dispatch comes from an executor thread via run_coroutine_threadsafe,
    which carries no boundary of its own — without this the transition's
    log.set() fields would be silently discarded.
    """
    async with log_context("composio_tool_integration_expiry", user_id=user_id):
        await expire_user_integration(
            user_id,
            integration_id,
            ExpiryOptions(reason=reason, trigger="tool_execution", notify=False),
        )


async def _expire_and_request_reconnect(
    user_id: str, integration_id: str, integration_name: str, reason: str
) -> str:
    """Mark the integration expired, then ask the user to reconnect.

    Ordered, not concurrent: the prompt reads the stored status to tell "expired"
    from "never connected", so racing the write would show first-time-connect copy
    for a connection that plainly died.
    """
    await _expire_with_log_boundary(user_id, integration_id, reason)
    return await request_integration_connection(integration_id, integration_name, user_id)


def _clean_reserved_keyword(keyword: str) -> str:
    return f"{keyword}_rs"


def _substitute_reserved_python_keywords(
    schema: _JsonSchema,
) -> tuple[_JsonSchema, dict[str, _RenamedKeyword]]:
    if "properties" not in schema:
        return schema, {}

    keywords: dict[str, _RenamedKeyword] = {}
    for p_name in list(schema["properties"]):
        if p_name not in _python_reserved:
            continue

        # Unmutated: nested is only ever read as a truth value, where None and {} agree.
        nested: dict[str, _RenamedKeyword] = {}  # pragma: no mutate
        p_val: _JsonSchema = schema["properties"].pop(p_name)
        if p_val.get("type") == "object":
            p_val, nested = _substitute_reserved_python_keywords(schema=p_val)

        p_name_clean = _clean_reserved_keyword(keyword=p_name)
        schema["properties"][p_name_clean] = p_val
        keywords[p_name_clean] = _RenamedKeyword(original=p_name, nested=nested)

    return schema, keywords


def _reinstate_reserved_python_keywords(
    request: dict[str, object], keywords: dict[str, _RenamedKeyword]
) -> dict[str, object]:
    for clean_key, renamed in keywords.items():
        if clean_key not in request:
            continue

        original_value = request.pop(clean_key)
        # LangChain hands an object argument over as its args-schema model, and as None when omitted.
        if renamed.nested and original_value is not None:
            nested_request = (
                original_value.model_dump(exclude_unset=True)
                if isinstance(original_value, pydantic.BaseModel)
                else t.cast(dict[str, object], original_value)
            )
            original_value = _reinstate_reserved_python_keywords(
                request=nested_request, keywords=renamed.nested
            )
        request[renamed.original] = original_value
    return request


_P = t.ParamSpec("_P")
_R = t.TypeVar("_R")


class ValidationFailure(t.TypedDict):
    """The failure result a tool call with invalid arguments returns instead of raising."""

    successful: bool
    error: str
    data: None


def _validation_failure_as_result(
    run: t.Callable[_P, _R],
) -> t.Callable[_P, _R | ValidationFailure]:
    """Wrap a tool's run so invalid arguments come back as a failure result, not a raise."""

    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R | ValidationFailure:
        try:
            # Unmutated: this wraps run at class definition, before mutmut can switch a
            # mutant in; replaying the edit shows TestInvalidArgumentsReturnAFailure fails.
            return run(*args, **kwargs)  # pragma: no mutate
        except pydantic.ValidationError as e:
            return {"successful": False, "error": parse_pydantic_error(e), "data": None}

    return wrapper


class StructuredTool(BaseStructuredTool):
    """StructuredTool that returns a structured failure instead of raising on invalid args."""

    run = _validation_failure_as_result(BaseStructuredTool.run)


class LangchainProvider(
    AgenticProvider[StructuredTool, list[StructuredTool]],
    name="langchain",
):
    """Composio toolset for Langchain framework."""

    runtime = "langchain"

    def __init__(self, **kwargs: t.Unpack[BaseProviderConfig]) -> None:
        super().__init__(**kwargs)
        # Wrapped tool callables are sync (executor thread) and can't await the
        # async expiry transition, so the loop they were built on is captured
        # here and dispatched via run_coroutine_threadsafe; wrap_tools tops it up if this capture missed the loop.
        self._loop: asyncio.AbstractEventLoop | None = _running_loop_or_none()

    def _handle_dead_connected_account(
        self,
        tool: str,
        toolkit: str | None,
        user_id: str | None,
        reason: str,
    ) -> dict[str, object]:
        """Reconcile a confirmed dead connected account and ask the user to reconnect.

        Marks the integration expired (so the integrations page, the tool registry
        and the pre-flight guard all stop treating it as usable) and hands the
        agent the connect instruction plus, on UI surfaces, the connect card.
        """
        integration = get_integration_by_toolkit(toolkit) if toolkit else None
        log.set(
            composio_tool_invocation={
                "tool": tool,
                "toolkit": toolkit,
                "user_id": user_id,
                "successful": False,
                "outcome": "dead_connected_account",
            }
        )
        log.warning(
            f"{LogTag.COMPOSIO} Composio tool failed on a dead connected account",
            tool=tool,
            toolkit=toolkit,
            user_id=user_id,
            integration_id=integration.id if integration else None,
            reason=reason[:200],
        )

        if integration is None:
            # A Composio toolkit with no GAIA integration behind it has no
            # connect affordance to offer — surface the failure as-is.
            return {"successful": False, "error": reason, "data": None}

        if user_id is None:
            # Trigger-option calls bind the user at get_tool(user_id=...) time, so
            # there is no user to expire and no chat stream to write to. The
            # webhook path covers this case with no dependency on chat context.
            return {"successful": False, "error": reason, "data": None}

        # This does not pause the workflows depending on the integration: that needs
        # the workflow layer, which cannot be imported from inside this wrapper. The
        # connection webhook is what pauses them, off the same dead account.
        message = self._run_on_loop(
            _expire_and_request_reconnect(user_id, integration.id, integration.name, reason),
            timeout=_RECONNECT_PROMPT_TIMEOUT_S,
        )

        return {"successful": False, "error": message or reason, "data": None}

    def _run_on_loop(
        self, coro: t.Coroutine[object, object, str | None], *, timeout: float
    ) -> str | None:
        """Await a coroutine on the captured loop from this executor thread, bounded."""
        if self._loop is None:
            coro.close()
            log.warning(f"{LogTag.COMPOSIO} No event loop captured — skipping the reconnect prompt")
            return None
        try:
            return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout)
        except TimeoutError:
            log.warning(
                f"{LogTag.COMPOSIO} Timed out building the reconnect prompt", timeout_s=timeout
            )
            return None

    def _wrap_action(
        self,
        tool: str,
        description: str,
        schema_params: _JsonSchema,
        execute_tool: AgenticProviderExecuteFn,
        keywords: dict[str, _RenamedKeyword],
        toolkit: str | None = None,
    ) -> types.FunctionType:
        def function(**kwargs: object) -> dict[str, object]:
            """Execute the composio action for this tool call."""

            call: _ToolCallTransport = t.cast(_ToolCallTransport, kwargs)
            # 'or {}' handles being called directly without LangChain (no config).
            runnable_config = call.get("__runnable_config__") or {}
            metadata: object = {}
            if isinstance(runnable_config, dict):
                config: RunnableConfig = t.cast(RunnableConfig, runnable_config)
                metadata = config.get("metadata", {})
            # user_id is read only for the observability log below; it's None for
            # trigger-option calls (bound at get_tool(user_id=...) time instead).
            # Harmless either way — Composio errors loudly if none reaches execution.
            user_id: str | None = None
            if isinstance(metadata, dict):
                run_metadata: _RunMetadataView = t.cast(_RunMetadataView, metadata)
                user_id = run_metadata.get("user_id")

            kwargs = _reinstate_reserved_python_keywords(
                request=kwargs,
                keywords=keywords,
            )

            kwargs["__runnable_config__"] = {"metadata": metadata}

            try:
                result = execute_tool(tool, kwargs)
            except composio_client.NotFoundError as e:
                # Only the dead-connected-account 404 is recoverable here. Any
                # other 404 — and every timeout, 5xx and genuine bug — must stay
                # loud so it still reaches Sentry.
                if not _is_dead_account_error(e):
                    raise
                return self._handle_dead_connected_account(tool, toolkit, user_id, str(e))

            # Surface tool invocation outcome for observability.
            try:
                succeeded: bool | None = None
                err_preview: str | None = None
                if isinstance(result, dict):
                    response: ToolExecutionResponse = t.cast(ToolExecutionResponse, result)
                    succeeded = response.get("successful")
                    if succeeded is False:
                        err_preview = str(response.get("error"))[:200]
                log.set(
                    composio_tool_invocation={
                        "tool": tool,
                        "toolkit": toolkit,
                        "user_id": user_id,
                        "successful": succeeded,
                    }
                )
                # Composio also reports a dead account without raising. That
                # string match is too loose to drive a state mutation, so this
                # stays a log line — but it shares the raising path's markers.
                if err_preview is not None:
                    if _message_mentions_dead_account(err_preview):
                        log.warning(
                            f"{LogTag.COMPOSIO} composio tool failed — likely a dead connected account",
                            tool=tool,
                            toolkit=toolkit,
                            user_id=user_id,
                            err_preview=err_preview,
                        )
                    else:
                        log.info(
                            f"{LogTag.COMPOSIO} composio tool returned successful=False",
                            tool=tool,
                            toolkit=toolkit,
                            user_id=user_id,
                            err_preview=err_preview,
                        )
            except Exception as obs_err:  # observability must not break tool
                log.debug(
                    f"{LogTag.COMPOSIO} composio invocation log skipped for",
                    tool=tool,
                    error=str(obs_err),
                    error_type=type(obs_err).__name__,
                )

            return result

        parameters = get_signature_format_from_schema_params(
            schema_params=t.cast(dict[str, object], schema_params)
        )

        parameters.append(
            Parameter(
                "__runnable_config__",
                kind=Parameter.KEYWORD_ONLY,
                default={},
                annotation=RunnableConfig,
            )
        )

        action_func = types.FunctionType(
            function.__code__,
            globals=globals(),
            name=tool,
            closure=function.__closure__,
        )
        # typeshed does not declare __signature__ on FunctionType, but inspect.signature()
        # honours it at runtime — that is how the tool's schema is advertised to LangChain.
        action_func.__signature__ = Signature(parameters=parameters)  # type: ignore[attr-defined]  # signature injected at runtime so FastAPI introspects synthesized tool params
        action_func.__doc__ = description

        # Create __annotations__ only for __runnable_config__
        action_func.__annotations__ = {"__runnable_config__": RunnableConfig}

        return action_func

    def wrap_tool(self, tool: Tool, execute_tool: AgenticProviderExecuteFn) -> StructuredTool:
        """Wrap a single Composio tool as a LangChain StructuredTool."""
        # Second chance at the loop capture: the provider singleton may have been
        # built off-loop by whichever caller hit the lazy provider first, but tools
        # are fetched per request from the running loop.
        if self._loop is None:
            self._loop = _running_loop_or_none()

        # Replace reserved python keywords
        schema_params, keywords = _substitute_reserved_python_keywords(
            schema=t.cast(_JsonSchema, tool.input_parameters)
        )

        # The provider's output schema feeds the Returns section of the execute
        # schema docs (schema_docs.py). A shapeless schema (no properties)
        # documents nothing, so it must not render a Returns section at all.
        output_parameters: _JsonSchema | None = (
            t.cast(_JsonSchema, tool.output_parameters)
            if isinstance(tool.output_parameters, dict)
            else None
        )
        metadata = (
            {"output_parameters": output_parameters}
            if output_parameters and output_parameters.get("properties")
            else None
        )

        return t.cast(
            StructuredTool,
            StructuredTool.from_function(
                name=tool.slug,
                description=tool.description,
                args_schema=json_schema_to_model(
                    json_schema=t.cast(dict[str, object], schema_params),
                    skip_default=self.skip_default,
                ),
                return_schema=True,
                func=self._wrap_action(
                    tool=tool.slug,
                    description=tool.description,
                    schema_params=schema_params,
                    execute_tool=execute_tool,
                    keywords=keywords,
                    toolkit=getattr(getattr(tool, "toolkit", None), "slug", None),
                ),
                handle_tool_error=True,
                handle_validation_error=True,
                metadata=metadata,
            ),
        )

    def wrap_tools(
        self,
        tools: t.Sequence[Tool],
        execute_tool: AgenticProviderExecuteFn,
    ) -> list[StructuredTool]:
        """Get composio tools wrapped as Langchain StructuredTool objects."""
        return [self.wrap_tool(tool=tool, execute_tool=execute_tool) for tool in tools]
