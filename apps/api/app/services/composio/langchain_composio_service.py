"""ComposioLangChain class definition"""

from inspect import Parameter, Signature
import types
import typing as t
import uuid

from composio.core.provider import AgenticProvider, AgenticProviderExecuteFn
from composio.types import Tool
from composio.utils.pydantic import parse_pydantic_error
from composio.utils.shared import (
    get_signature_format_from_schema_params,
    json_schema_to_model,
)
from langchain_core.callbacks import Callbacks
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import StructuredTool as BaseStructuredTool
import pydantic

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

_python_reserved = {"for", "async", "from", "import", "as", "pass", "continue"}
_obj_marker = "-_object_-"


def _clean_reserved_keyword(keyword: str) -> str:
    return f"{keyword}_rs"


def _substitute_reserved_python_keywords(
    schema: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    if "properties" not in schema:
        return schema, {}

    properties = schema["properties"]
    if not isinstance(properties, dict):
        raise ValueError(f"Expected 'properties' to be a dict, got {type(properties).__name__}")

    keywords: dict[str, object] = {}
    for p_name in list(properties):
        if p_name not in _python_reserved:
            continue

        _keywords: dict[str, object] = {}
        p_val = properties.pop(p_name)
        if not isinstance(p_val, dict):
            raise ValueError(
                f"Expected property {p_name!r} schema to be a dict, got {type(p_val).__name__}"
            )
        if p_val.get("type") == "object":
            p_val, _keywords = _substitute_reserved_python_keywords(schema=p_val)

        p_name_clean = _clean_reserved_keyword(keyword=p_name)
        properties[p_name_clean] = p_val
        keywords[p_name_clean] = p_name
        keywords[f"{p_name_clean}{_obj_marker}"] = _keywords

    return schema, keywords


def _reinstate_reserved_python_keywords(
    request: dict[str, object], keywords: dict[str, object]
) -> dict[str, object]:
    for clean_key in sorted(list(keywords), reverse=True):
        subkeys: dict[str, object] | None = None
        if clean_key.endswith(_obj_marker):
            marker_value = keywords[clean_key]
            if not isinstance(marker_value, dict):
                raise ValueError(
                    f"Expected {clean_key!r} marker to hold a keyword map, "
                    f"got {type(marker_value).__name__}"
                )
            subkeys = marker_value
            clean_key, _ = clean_key.split(_obj_marker, maxsplit=1)

        if clean_key not in request:
            continue

        original_value = request.pop(clean_key)
        # Empty subkeys (a nested object whose reserved properties were all
        # leaves) is the normal scalar case: nothing to reinstate inside.
        if subkeys:
            if not isinstance(original_value, dict):
                raise ValueError(
                    f"Expected {clean_key!r} value to be a dict for keyword "
                    f"reinstatement, got {type(original_value).__name__}"
                )
            original_value = _reinstate_reserved_python_keywords(
                request=original_value,
                keywords=subkeys,
            )
        original_key = keywords[clean_key]
        if not isinstance(original_key, str):
            raise ValueError(
                f"Expected {clean_key!r} to map to a keyword name, "
                f"got {type(original_key).__name__}"
            )
        request[original_key] = original_value
    return request


class StructuredTool(BaseStructuredTool):  # type: ignore[explicit-any]
    """StructuredTool that returns a structured failure instead of raising on invalid args."""

    def run(
        self,
        tool_input: str | dict[str, object],
        verbose: bool | None = None,
        start_color: str | None = "green",
        color: str | None = "green",
        callbacks: Callbacks = None,
        *,
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        run_name: str | None = None,
        run_id: uuid.UUID | None = None,
        config: RunnableConfig | None = None,
        tool_call_id: str | None = None,
        **kwargs: object,
    ) -> object:
        """Run the tool, converting argument validation errors into a failure result."""
        try:
            return super().run(
                tool_input,
                verbose=verbose,
                start_color=start_color,
                color=color,
                callbacks=callbacks,
                tags=tags,
                metadata=metadata,
                run_name=run_name,
                run_id=run_id,
                config=config,
                tool_call_id=tool_call_id,
                **kwargs,
            )
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

    def _wrap_action(
        self,
        tool: str,
        description: str,
        schema_params: dict[str, object],
        execute_tool: AgenticProviderExecuteFn,
        keywords: dict[str, object],
        toolkit: str | None = None,
    ) -> types.FunctionType:
        def function(**kwargs: object) -> dict[str, object]:
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

            result = execute_tool(tool, kwargs)

            # Surface tool invocation outcome for observability.
            try:
                succeeded = result.get("successful") if isinstance(result, dict) else None
                err_preview = (
                    str(result.get("error"))[:200]
                    if isinstance(result, dict) and not succeeded
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
                if succeeded is False:
                    err_lower = (err_preview or "").lower()
                    looks_like_dead_account = (
                        "1810" in err_lower
                        or "no active connected account" in err_lower
                        or "no connected account" in err_lower
                    )
                    if looks_like_dead_account:
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
            except Exception as obs_err:  # noqa: BLE001 - observability must not break tool
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
