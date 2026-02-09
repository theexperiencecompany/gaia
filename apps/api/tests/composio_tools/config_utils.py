"""
Configuration utilities for Composio tool tests.

Loads config from config.yaml with environment variable interpolation.
Environment variables are referenced using ${VAR_NAME} syntax.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import yaml  # type: ignore[import-untyped]
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Path to config file (same directory as this module)
CONFIG_PATH = Path(__file__).parent / "config.yaml"

# Regex to match ${VAR_NAME} patterns
ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")

_config_cache: Optional[Dict[str, Any]] = None


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand ${VAR} patterns in config values."""
    if isinstance(value, str):

        def replace_var(match):
            var_name = match.group(1)
            return os.environ.get(var_name, "")

        return ENV_VAR_PATTERN.sub(replace_var, value)
    elif isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_expand_env_vars(item) for item in value]
    return value


def load_config(reload: bool = False) -> Dict[str, Any]:
    """
    Load and parse config file with env var expansion.

    Args:
        reload: If True, reload from disk even if cached

    Returns:
        Parsed config dictionary with env vars expanded
    """
    global _config_cache

    if _config_cache is not None and not reload:
        return _config_cache

    if not CONFIG_PATH.exists():
        # Return minimal config if file doesn't exist
        return {
            "common": {"user_id": os.environ.get("EVAL_USER_ID", "")},
        }

    with open(CONFIG_PATH) as f:
        raw_config = yaml.safe_load(f) or {}

    _config_cache = _expand_env_vars(raw_config)
    return _config_cache or {}


def get_common_config() -> Dict[str, Any]:
    """Get common settings shared by all integrations."""
    config = load_config()
    return config.get("common", {})


def get_user_id() -> str:
    """Get the test user ID from config or environment."""
    common = get_common_config()
    user_id = common.get("user_id", "")
    if not user_id:
        # Fallback to direct env var check
        user_id = os.environ.get("EVAL_USER_ID", "")
    return user_id


def get_integration_config(integration: str) -> Dict[str, Any]:
    """
    Get config for a specific integration, merged with common settings.

    Args:
        integration: Integration name (e.g., 'gmail', 'notion')

    Returns:
        Merged config dict with common + integration-specific settings
    """
    config = load_config()
    common = config.get("common", {})
    integration_config = config.get(integration, {})

    # Merge: integration-specific overrides common
    merged = {**common, **integration_config}
    return merged


# Integration name mapping to test file names
INTEGRATION_MAP = {
    "calendar": "test_calendar",
    "googlecalendar": "test_calendar",
    "gmail": "test_gmail",
    "googledocs": "test_googledocs",
    "docs": "test_googledocs",
    "googlesheets": "test_googlesheets",
    "sheets": "test_googlesheets",
    "linear": "test_linear",
    "linkedin": "test_linkedin",
    "notion": "test_notion",
    "twitter": "test_twitter",
}

ALL_INTEGRATIONS = [
    "calendar",
    "gmail",
    "googledocs",
    "googlesheets",
    "linear",
    "linkedin",
    "notion",
    "twitter",
]


def get_test_file(integration: str) -> Optional[str]:
    """
    Map integration name to test file name.

    Args:
        integration: Integration name (e.g., 'gmail', 'sheets')

    Returns:
        Test file name without .py extension, or None if not found
    """
    return INTEGRATION_MAP.get(integration.lower())
