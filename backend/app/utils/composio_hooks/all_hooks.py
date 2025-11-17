"""
Auto-registration of all hooks.

This module automatically imports all hook modules to trigger their decorators.
Just importing this module will register all hooks automatically.
"""

# Import all hook modules to trigger their decorators
from . import (
    gmail_hooks,  # noqa: F401
    user_id_hooks,  # noqa: F401
)

# Add any new hook modules here and they'll be auto-registered
# from . import new_hook_module  # noqa: F401
