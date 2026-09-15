"""
Core registry and master hooks for Composio tool system.

This module provides the central registry and master execution hooks that handle
ALL Composio tools with built-in user_id extraction and frontend streaming.

Also provides schema modifiers for customizing tool schemas before they are
presented to agents.
"""

from collections.abc import Callable
from typing import Union, cast

from composio.types import Tool, ToolExecuteParams, ToolExecutionResponse
from pydantic import ValidationError

from app.constants.log_tags import LogTag
from app.models.integrations.composio_hooks import ComposioToolCall, RunnableConfigTransport
from shared.py.wide_events import log

# Most after-hooks return a narrower dict built from the envelope's data field,
# but gmail_attachment_after_hook legitimately passes through a non-dict data
# value unprocessed — so the honest type here is "whatever the payload is."
AfterHookResponse = object
BeforeHookFn = Callable[[str, str, ToolExecuteParams], ToolExecuteParams]
AfterHookFn = Callable[[str, str, ToolExecutionResponse], AfterHookResponse]
SchemaModifierFn = Callable[[str, str, Tool], Tool]


class HookAbortError(Exception):
    """A before-hook signal that the tool call MUST NOT proceed.

    Ordinary before-hook exceptions are swallowed (a hook is enrichment: a bug in
    one must not fail the tool). This one is different — it means the hook found a
    condition that makes executing the tool wrong (e.g. a requested attachment
    could not be resolved), so letting the call run would produce a silently
    incorrect result. execute_before_hooks re-raises it so it propagates
    through Composio's executor and fails the tool loudly.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ComposioHookRegistry:
    """Registry for before_execute, after_execute, and schema-modifier hooks.

    A single master hook system supports conditional execution by tool/toolkit.
    """

    def __init__(self) -> None:
        # Registry for before_execute hooks
        self._before_hooks: list[BeforeHookFn] = []

        # Registry for after_execute hooks
        self._after_hooks: list[AfterHookFn] = []

        # Registry for schema modifiers
        self._schema_modifiers: list[SchemaModifierFn] = []

    def register_before_hook(self, hook_func: BeforeHookFn) -> None:
        """Register a before_execute hook function."""
        self._before_hooks.append(hook_func)
        log.debug(
            f"{LogTag.COMPOSIO} Registered before_execute hook", hook_func_name=hook_func.__name__
        )

    def register_after_hook(self, hook_func: AfterHookFn) -> None:
        """Register an after_execute hook function."""
        self._after_hooks.append(hook_func)
        log.debug(
            f"{LogTag.COMPOSIO} Registered after_execute hook", hook_func_name=hook_func.__name__
        )

    def execute_before_hooks(
        self, tool: str, toolkit: str, params: ToolExecuteParams
    ) -> ToolExecuteParams:
        """Execute all registered before_execute hooks."""
        log.set(composio_tool=tool, composio_toolkit=toolkit)
        modified_params = params
        for hook_func in self._before_hooks:
            try:
                modified_params = hook_func(tool, toolkit, modified_params)
            except HookAbortError:
                # An explicit "do not run this tool" signal — propagate so the
                # executor fails the call instead of running it with a wrong /
                # missing argument (see HookAbortError).
                raise
            except Exception as e:
                log.error(
                    f"{LogTag.COMPOSIO} Error executing before_execute hook for",
                    hook_func_name=hook_func.__name__,
                    tool=tool,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                # Continue with other hooks even if one fails
        return modified_params

    def execute_after_hooks(
        self, tool: str, toolkit: str, response: ToolExecutionResponse
    ) -> AfterHookResponse:
        """Execute all registered after_execute hooks."""
        modified_response: AfterHookResponse = response
        for hook_func in self._after_hooks:
            try:
                # Registrations are mutually exclusive, so at most one hook in the
                # chain ever narrows the envelope; modified_response stays the
                # pristine ToolExecutionResponse until a match fires.
                modified_response = hook_func(
                    tool, toolkit, cast(ToolExecutionResponse, modified_response)
                )
            except Exception as e:
                log.error(
                    f"{LogTag.COMPOSIO} Error executing after_execute hook for",
                    hook_func_name=hook_func.__name__,
                    tool=tool,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                # Continue with other hooks even if one fails
        return modified_response

    def register_schema_modifier(self, modifier_func: SchemaModifierFn) -> None:
        """Register a schema modifier function."""
        self._schema_modifiers.append(modifier_func)
        log.debug(
            f"{LogTag.COMPOSIO} Registered schema_modifier",
            modifier_func_name=modifier_func.__name__,
        )

    def execute_schema_modifiers(self, tool: str, toolkit: str, schema: Tool) -> Tool:
        """Execute all registered schema modifiers."""
        modified_schema = schema
        for modifier_func in self._schema_modifiers:
            try:
                modified_schema = modifier_func(tool, toolkit, modified_schema)
            except Exception as e:
                log.error(
                    f"{LogTag.COMPOSIO} Error executing schema_modifier for",
                    modifier_func_name=modifier_func.__name__,
                    tool=tool,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                # Continue with other modifiers even if one fails
        return modified_schema


# Global registry instance
hook_registry = ComposioHookRegistry()


def _resolve_call_identity(tool: str, toolkit: str, params: ToolExecuteParams) -> None:
    """Establish the calling user from RunnableConfig metadata, ahead of every hook.

    Runs first because hooks must never see a stale or model-supplied user_id: our injected id wins on conflict (logged), and trigger flows (no metadata) keep the SDK's bound id. __runnable_config__ is popped as transport, not a tool argument; entity_id is set alongside user_id for Composio's legacy connected-account auth.
    """
    # Real params arrive as plain dicts that may omit keys or carry non-dict
    # values; a call that does not parse simply carries no identity to resolve.
    try:
        call = ComposioToolCall.model_validate(params)
    except ValidationError:
        return
    config = call.arguments.pop("__runnable_config__", None)
    params["arguments"] = call.arguments
    if not isinstance(config, dict):
        return
    try:
        transport = RunnableConfigTransport.model_validate(config)
    except ValidationError:
        return
    user_id = transport.metadata.user_id if transport.metadata else None
    if not user_id:
        return
    if call.user_id and call.user_id != user_id:
        log.warning(
            f"{LogTag.COMPOSIO} Hook user_id overwritten from RunnableConfig",
            tool=tool,
            toolkit=toolkit,
        )
    params["user_id"] = user_id
    params["entity_id"] = user_id


def master_before_execute_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """
    Master before_execute hook that handles ALL tools.

    This includes:
    1. User ID extraction from RunnableConfig metadata
    2. Frontend streaming setup
    3. All registered tool-specific hooks
    """
    log.set(composio_tool=tool, composio_toolkit=toolkit)
    _resolve_call_identity(tool, toolkit, params)
    return hook_registry.execute_before_hooks(tool, toolkit, params)


def master_after_execute_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> ToolExecutionResponse:
    """Master after_execute hook that runs all registered tool-specific hooks and global transforms.

    Composio's AfterExecute protocol declares this returns ToolExecutionResponse, but hooks legitimately return a trimmed dict (AfterHookResponse); the cast here matches the SDK's own runtime behavior, which casts to Dict without enforcing the shape either.
    """
    result = hook_registry.execute_after_hooks(tool, toolkit, response)
    return cast(ToolExecutionResponse, result)


def master_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """Master schema modifier that runs all registered schema modifiers before a tool schema reaches an agent."""
    return hook_registry.execute_schema_modifiers(tool, toolkit, schema)


def register_before_hook(
    tools: Union[str, list[str]] | None = None,
    toolkits: Union[str, list[str]] | None = None,
) -> Callable[[BeforeHookFn], BeforeHookFn]:
    """Register a decorator that scopes a before_execute hook to specific tools or toolkits (all if omitted)."""

    def decorator(func: BeforeHookFn) -> BeforeHookFn:
        # Normalize tools and toolkits to lists
        target_tools = []
        if tools:
            target_tools = [tools] if isinstance(tools, str) else tools

        target_toolkits = []
        if toolkits:
            target_toolkits = [toolkits] if isinstance(toolkits, str) else toolkits

        def conditional_hook(
            tool: str, toolkit: str, params: ToolExecuteParams
        ) -> ToolExecuteParams:
            # Check if this hook should run for this tool/toolkit
            should_run = False

            # If no specific tools/toolkits specified, run for all
            if not target_tools and not target_toolkits:
                should_run = True
            else:
                # Check tool match
                if target_tools and tool in target_tools:
                    should_run = True
                # Check toolkit match
                if target_toolkits and toolkit in target_toolkits:
                    should_run = True

            if should_run:
                return func(tool, toolkit, params)
            return params

        hook_registry.register_before_hook(conditional_hook)
        return func

    return decorator


def register_after_hook(
    tools: Union[str, list[str]] | None = None,
    toolkits: Union[str, list[str]] | None = None,
) -> Callable[[AfterHookFn], AfterHookFn]:
    """Register a decorator that scopes an after_execute hook to specific tools or toolkits (all if omitted)."""

    def decorator(func: AfterHookFn) -> AfterHookFn:
        # Normalize tools and toolkits to lists
        target_tools = []
        if tools:
            target_tools = [tools] if isinstance(tools, str) else tools

        target_toolkits = []
        if toolkits:
            target_toolkits = [toolkits] if isinstance(toolkits, str) else toolkits

        def conditional_hook(
            tool: str, toolkit: str, response: ToolExecutionResponse
        ) -> AfterHookResponse:
            # Check if this hook should run for this tool/toolkit
            should_run = False

            # If no specific tools/toolkits specified, run for all
            if not target_tools and not target_toolkits:
                should_run = True
            else:
                # Check tool match
                if target_tools and tool in target_tools:
                    should_run = True
                # Check toolkit match
                if target_toolkits and toolkit in target_toolkits:
                    should_run = True

            if should_run:
                return func(tool, toolkit, response)
            return response

        hook_registry.register_after_hook(conditional_hook)
        return func

    return decorator


def register_schema_modifier(
    tools: Union[str, list[str]] | None = None,
    toolkits: Union[str, list[str]] | None = None,
) -> Callable[[SchemaModifierFn], SchemaModifierFn]:
    """Register a decorator that scopes a schema modifier to specific tools or toolkits (all if omitted)."""

    def decorator(func: SchemaModifierFn) -> SchemaModifierFn:
        # Normalize tools and toolkits to lists
        target_tools = []
        if tools:
            target_tools = [tools] if isinstance(tools, str) else tools

        target_toolkits = []
        if toolkits:
            target_toolkits = [toolkits] if isinstance(toolkits, str) else toolkits

        def conditional_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
            # Check if this modifier should run for this tool/toolkit
            should_run = False

            # If no specific tools/toolkits specified, run for all
            if not target_tools and not target_toolkits:
                should_run = True
            else:
                # Check tool match
                if target_tools and tool in target_tools:
                    should_run = True
                # Check toolkit match
                if target_toolkits and toolkit in target_toolkits:
                    should_run = True

            if should_run:
                return func(tool, toolkit, schema)
            return schema

        hook_registry.register_schema_modifier(conditional_modifier)
        return func

    return decorator
