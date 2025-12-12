"""
Core registry and master hooks for Composio tool system.

This module provides the central registry and master execution hooks that handle
ALL Composio tools with built-in user_id extraction and frontend streaming.
"""

from typing import Any, Callable, List, Optional, Union

from app.config.loggers import app_logger as logger
from composio.types import ToolExecuteParams


class ComposioHookRegistry:
    """
    Enhanced registry for managing before_execute and after_execute hooks.

    Supports conditional execution based on tool name/toolkit with a single
    master hook system that handles ALL tools.
    """

    def __init__(self) -> None:
        # Registry for before_execute hooks
        self._before_hooks: List[
            Callable[[str, str, ToolExecuteParams], ToolExecuteParams]
        ] = []

        # Registry for after_execute hooks
        self._after_hooks: List[Callable[[str, str, Any], Any]] = []

    def register_before_hook(
        self, hook_func: Callable[[str, str, ToolExecuteParams], ToolExecuteParams]
    ) -> None:
        """Register a before_execute hook function."""
        self._before_hooks.append(hook_func)
        logger.debug(f"Registered before_execute hook: {hook_func.__name__}")

    def register_after_hook(self, hook_func: Callable[[str, str, Any], Any]) -> None:
        """Register an after_execute hook function."""
        self._after_hooks.append(hook_func)
        logger.debug(f"Registered after_execute hook: {hook_func.__name__}")

    def execute_before_hooks(
        self, tool: str, toolkit: str, params: ToolExecuteParams
    ) -> ToolExecuteParams:
        """Execute all registered before_execute hooks."""
        modified_params = params
        for hook_func in self._before_hooks:
            try:
                modified_params = hook_func(tool, toolkit, modified_params)
            except Exception as e:
                logger.error(
                    f"Error executing before_execute hook {hook_func.__name__} for {tool}: {e}"
                )
                # Continue with other hooks even if one fails
        return modified_params

    def execute_after_hooks(self, tool: str, toolkit: str, response: Any) -> Any:
        """Execute all registered after_execute hooks."""
        modified_response = response
        for hook_func in self._after_hooks:
            try:
                modified_response = hook_func(tool, toolkit, modified_response)
            except Exception as e:
                logger.error(
                    f"Error executing after_execute hook {hook_func.__name__} for {tool}: {e}"
                )
                # Continue with other hooks even if one fails
        return modified_response


# Global registry instance
hook_registry = ComposioHookRegistry()


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
    return hook_registry.execute_before_hooks(tool, toolkit, params)


def master_after_execute_hook(tool: str, toolkit: str, response: Any) -> Any:
    """
    Master after_execute hook that handles ALL tools.

    This includes:
    1. All registered tool-specific output processing hooks
    2. Any global response transformations
    """
    # Execute all registered tool-specific hooks
    return hook_registry.execute_after_hooks(tool, toolkit, response)


def register_before_hook(
    tools: Optional[Union[str, List[str]]] = None,
    toolkits: Optional[Union[str, List[str]]] = None,
):
    """
    Enhanced decorator for registering before_execute hooks.

    Args:
        tools: Single tool name or list of tool names to target
        toolkits: Single toolkit name or list of toolkit names to target

    Usage:
        @register_before_hook(tools=["GMAIL_FETCH_EMAILS", "GMAIL_SEND_EMAIL"])
        def gmail_param_modifier(tool, toolkit, params):
            if tool == "GMAIL_FETCH_EMAILS":
                # Handle fetch emails params
                pass
            elif tool == "GMAIL_SEND_EMAIL":
                # Handle send email params
                pass
            return params

        @register_before_hook(toolkits="GMAIL")
        def gmail_toolkit_modifier(tool, toolkit, params):
            if toolkit == "GMAIL":
                # Handle all Gmail tools
                pass
            return params
    """

    def decorator(func: Callable[[str, str, ToolExecuteParams], ToolExecuteParams]) -> Callable[[str, str, ToolExecuteParams], ToolExecuteParams]:
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
    tools: Optional[Union[str, List[str]]] = None,
    toolkits: Optional[Union[str, List[str]]] = None,
):
    """
    Enhanced decorator for registering after_execute hooks.

    Args:
        tools: Single tool name or list of tool names to target
        toolkits: Single toolkit name or list of toolkit names to target

    Usage:
        @register_after_hook(tools=["GMAIL_FETCH_EMAILS"])
        def gmail_output_processor(tool, toolkit, response):
            if tool == "GMAIL_FETCH_EMAILS":
                # Process Gmail fetch response
                pass
            return response

        @register_after_hook(toolkits="GMAIL")
        def gmail_toolkit_processor(tool, toolkit, response):
            if toolkit == "GMAIL":
                # Process all Gmail tool responses
                pass
            return response
    """

    def decorator(func: Callable[[str, str, Any], Any]) -> Callable[[str, str, Any], Any]:
        # Normalize tools and toolkits to lists
        target_tools = []
        if tools:
            target_tools = [tools] if isinstance(tools, str) else tools

        target_toolkits = []
        if toolkits:
            target_toolkits = [toolkits] if isinstance(toolkits, str) else toolkits

        def conditional_hook(tool: str, toolkit: str, response: Any) -> Any:
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
