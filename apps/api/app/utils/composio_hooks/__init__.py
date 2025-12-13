"""
Enhanced Composio Hook System

A clean, powerful hook system for Composio tools with:
- Single master before/after executors for ALL tools
- Enhanced decorators supporting multiple tools/toolkits
- Conditional logic based on tool name/toolkit
- Integrated user_id extraction and frontend streaming

Auto-registration: Simply import this module and all hooks are automatically registered.
"""

# Auto-import all hook modules to trigger registration
from . import all_hooks  # noqa: F401
from .registry import (
    hook_registry,
    master_after_execute_hook,
    master_before_execute_hook,
    register_after_hook,
    register_before_hook,
)

__all__ = [
    "hook_registry",
    "master_before_execute_hook",
    "master_after_execute_hook",
    "register_before_hook",
    "register_after_hook",
]
