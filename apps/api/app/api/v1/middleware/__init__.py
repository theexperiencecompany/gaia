"""API v1 middleware package.

Deliberately empty. Re-exports here made importing the rate limiter execute
auth too, so every importer paid workos and the whole middleware stack
(131 modules, ~0.2 s). Import each middleware from its own module.

tiered_rate_limit lives in app/decorators/rate_limiting.py; a second copy here
once drifted and silently skipped rate limiting.
"""
