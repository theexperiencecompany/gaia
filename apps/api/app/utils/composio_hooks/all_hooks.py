"""
Auto-registration of all hooks.

This module automatically imports all hook modules to trigger their decorators.
Just importing this module will register all hooks automatically.
"""

# Import all hook modules to trigger their decorators
from . import (
    gmail_hooks,  # noqa: F401 -- imported for @register_hook side effects
    reddit_hooks,  # noqa: F401 -- imported for @register_hook side effects
    slack_hooks,  # noqa: F401 -- imported for @register_hook side effects
    twitter_hooks,  # noqa: F401 -- imported for @register_hook side effects
    user_id_hooks,  # noqa: F401 -- imported for @register_hook side effects
)

# Add any new hook modules here and they'll be auto-registered
# from . import new_hook_module
