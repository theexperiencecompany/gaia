"""
This module contains patches for various components to ensure compatibility and fix issues.
"""

from . import (
    composio_custom_tool_patch,
    composio_custom_tool_schema_patch,
    composio_langchain_patch,
    langchain_merge_dicts_model_name_patch,
    openrouter_cumulative_usage_patch,
    openrouter_tool_multimodal_patch,
)

# Apply these patches explicitly here so the patch modules themselves have no
# import-time side effect — mutmut cannot grade modules that invoke functions
# at import time (its trampoline aborts with "Unable to force test failures").
from .openrouter_provider_name_patch import apply as _apply_provider_name
from .openrouter_stream_finish_reason_patch import (
    apply as _apply_stream_finish_reason,
)

_apply_stream_finish_reason()
_apply_provider_name()
