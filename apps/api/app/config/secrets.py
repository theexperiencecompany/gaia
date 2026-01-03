"""
Infisical secrets management for GAIA API.

Re-exports from gaia_shared.secrets for backward compatibility.
"""

# Re-export from shared library
from shared.py.secrets import (
    InfisicalConfigError,
    inject_infisical_secrets,
)

__all__ = [
    "inject_infisical_secrets",
    "InfisicalConfigError",
]
