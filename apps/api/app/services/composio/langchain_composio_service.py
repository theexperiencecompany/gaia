"""ComposioLangChain class definition"""

import asyncio
from inspect import Parameter, Signature
import types
import typing as t

from composio.core.provider import AgenticProvider, AgenticProviderExecuteFn
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
from app.services.integrations.integration_expiry import expire_user_integration
from app.utils.integration_checker import request_integration_connection
from shared.py.wide_events import log, log_context

_python_reserved = {"for", "async", "from", "import", "as", "pass", "continue"}
_obj_marker = "-_object_-"

# Composio's tool-execute failure for a connected account that is missing, expired
# or revoked: error code 1810, name `ActionExecute_ConnectedAccountNotFound`. It
# surfaces two ways — as a raised `composio_client.NotFoundError` (404) and as a
# non-raising `{"successful": False, "error": "..."}` result — so both paths gate
# on this one marker set rather than on two drifting copies.
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
        detail = body.get("error") if isinstance(body.get("error"), dict) else body
        if isinstance(detail, dict):
            code = detail.get("error_code", detail.get("code"))
            name = detail.get("name", detail.get("type"))
            if str(code) == _DEAD_ACCOUNT_ERROR_CODE:
                return True
            if isinstance(name, str) and name.lower() == _DEAD_ACCOUNT_ERROR_NAME:
                return True
    return _message_mentions_dead_account(str(error))


async def _expire_with_log_boundary(user_id: str, integration_id: str, reason: str) -> None:
    """Run the expiry transition under its own wide-event boundary.

    The dispatch comes from an executor thread via ``run_coroutine_threadsafe``,
    which carries no boundary of its own — without this the transition's
    ``log.set()`` fields would be silently discarded.
    """
    async with log_context("composio_tool_integration_expiry", user_id=user_id):
        await expire_user_integration(
            user_id,
            integration_id,
            reason=reason,
            trigger="tool_execution",
            notify=False,
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
    schema: dict[str, t.Any],
) -> tuple[dict[str, t.Any], dict[str, t.Any]]:
    if "properties" not in schema:
        return schema, {}

    keywords: dict[str, t.Any] = {}
    for p_name in list(schema["properties"]):
        if p_name not in _python_reserved:
            continue

        _keywords: dict[str, t.Any] = {}
        p_val = schema["properties"].pop(p_name)
        if p_val.get("type") == "object":
            p_val, _keywords = _substitute_reserved_python_keywords(schema=p_val)

        p_name_clean = _clean_reserved_keyword(keyword=p_name)
        schema["properties"][p_name_clean] = p_val
        keywords[p_name_clean] = p_name
        keywords[f"{p_name_clean}{_obj_marker}"] = _keywords

    return schema, keywords


def _reinstate_reserved_python_keywords(
    request: dict[str, t.Any], keywords: dict[str, t.Any]
) -> dict[str, t.Any]:
    for clean_key in sorted(list(keywords), reverse=True):
        subkeys = None
        if clean_key.endswith(_obj_marker):
            subkeys = keywords[clean_key]
            clean_key, _ = clean_key.split(_obj_marker, maxsplit=1)

        if clean_key not in request:
            continue

        orginal_value = request.pop(clean_key)
        if subkeys is not None:
            orginal_value = _reinstate_reserved_python_keywords(
                request=orginal_value,
                keywords=subkeys,
            )
        request[keywords[clean_key]] = orginal_value
    return request


class StructuredTool(BaseStructuredTool):
    """StructuredTool that returns a structured failure instead of raising on invalid args."""

    def run(self, *args: t.Any, **kwargs: t.Any) -> t.Any:
        """Run the tool, converting argument validation errors into a failure result."""
        try:
            return super().run(*args, **kwargs)
        except pydantic.ValidationError as e:
            return {"successful": False, "error": parse_pydantic_error(e), "data": None}


class LangchainProvider(
    AgenticProvider[StructuredTool, list[StructuredTool]],
    name="langchain",
):
    """
    Composio toolset for Langchain framework.
    """

    runtime = "langchain"

    def __init__(self, **kwargs: t.Any) -> None:
        super().__init__(**kwargs)
        # The wrapped tool callables are sync and run in an executor thread, so
        # they cannot await the async expiry transition. Hold the loop they were
        # built on and dispatch onto it with run_coroutine_threadsafe. Capture is
        # best-effort here because the provider is built by a lazy provider whose
        # first caller may not be on the loop — wrap_tools tops it up.
        self._loop: asyncio.AbstractEventLoop | None = _running_loop_or_none()

    def _handle_dead_connected_account(
        self,
        tool: str,
        toolkit: str | None,
        user_id: str | None,
        reason: str,
    ) -> dict[str, t.Any]:
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
        self, coro: t.Coroutine[t.Any, t.Any, str | None], *, timeout: float
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
        schema_params: dict[str, t.Any],
        execute_tool: AgenticProviderExecuteFn,
        keywords: dict[str, t.Any],
        toolkit: str | None = None,
    ) -> types.FunctionType:
        def function(**kwargs: t.Any) -> dict[str, t.Any]:
            """Wrapper function for composio action."""

            # Discarding other data except metadata from __runnable_config__
            # Use 'or {}' to handle None case when called directly without LangChain
            runnable_config = kwargs.get("__runnable_config__") or {}
            metadata = (
                runnable_config.get("metadata", {}) if isinstance(runnable_config, dict) else {}
            )
            # user_id is read only for the observability log below. It is present
            # for agent-flow calls (which pass it in config metadata) and None for
            # trigger-option calls (which bind the user at get_tool(user_id=...)
            # time — invisible here but still used for auth at execution). Identity
            # is resolved at execution, not here, so a None is harmless; Composio
            # errors loudly if no user_id reaches it either way.
            user_id = metadata.get("user_id") if isinstance(metadata, dict) else None

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
                succeeded = result.get("successful") if isinstance(result, dict) else None
                err_preview = (
                    str(result.get("error"))[:200]
                    if isinstance(result, dict) and succeeded is False
                    else None
                )
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

        parameters = get_signature_format_from_schema_params(schema_params=schema_params)

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
        action_func.__signature__ = Signature(parameters=parameters)  # type: ignore[attr-defined]
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
        schema_params, keywords = _substitute_reserved_python_keywords(schema=tool.input_parameters)

        return t.cast(
            StructuredTool,
            StructuredTool.from_function(
                name=tool.slug,
                description=tool.description,
                args_schema=json_schema_to_model(
                    json_schema=schema_params,
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
            ),
        )

    def wrap_tools(
        self,
        tools: t.Sequence[Tool],
        execute_tool: AgenticProviderExecuteFn,
    ) -> list[StructuredTool]:
        """
        Get composio tools wrapped as Langchain StructuredTool objects.
        """
        return [self.wrap_tool(tool=tool, execute_tool=execute_tool) for tool in tools]
