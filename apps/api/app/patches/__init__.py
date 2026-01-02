"""
This module contains patches for various components to ensure compatibility and fix issues.
"""

from . import (
    composio_custom_tool_patch,  # noqa: F401
    composio_schema_patch,  # noqa: F401
    jsonplus,  # noqa: F401
)

# Apply the schema patch on import
composio_schema_patch.apply()
