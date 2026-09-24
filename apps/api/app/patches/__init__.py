"""Apply patches to third-party components for compatibility and bug fixes."""

from . import (
    browser_use_click_patch,
    browser_use_event_budget_patch,
    browser_use_input_timing_patch,
    browser_use_obscura_navigate_patch,
    browser_use_page_ready_patch,
    browser_use_read_result_patch,
    browser_use_run_lock_patch,
    browser_use_scroll_patch,
    browser_use_select_patch,
    browser_use_stealth_patch,
    browser_use_window_open_patch,
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
from .composio_custom_tool_input_patch import apply as _apply_custom_tool_input
from .openrouter_provider_name_patch import apply as _apply_provider_name
from .openrouter_stream_finish_reason_patch import (
    apply as _apply_stream_finish_reason,
)

_apply_stream_finish_reason()
_apply_provider_name()
_apply_custom_tool_input()
