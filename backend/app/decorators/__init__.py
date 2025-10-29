"""
Decorators package for GAIA backend.
"""

from .caching import Cacheable, CacheInvalidator
from .calendar_auth import with_calendar_auth
from .documentation import with_doc
from .integration import require_integration
from .rate_limiting import (
    with_rate_limiting,
    tiered_rate_limit,
    LangChainRateLimitException,
    set_user_context,
    clear_user_context,
    get_current_rate_limit_info,
)

__all__ = [
    # Documentation
    "with_doc",
    # Rate limiting
    "with_rate_limiting",
    "tiered_rate_limit",
    "LangChainRateLimitException",
    "set_user_context",
    "clear_user_context",
    "get_current_rate_limit_info",
    # Integration
    "require_integration",
    # Calendar auth
    "with_calendar_auth",
    # Caching
    "Cacheable",
    "CacheInvalidator",
]
