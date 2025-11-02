"""
Infisical secrets management for Gaia production environments.

Infisical streamlines environment variable sharing within the Gaia team for
production and staging deployments. Not required for self-hosting or
contributor development - use local .env files and refer to the docs
configuration section instead.

Local environment variables take precedence over Infisical secrets.
"""

import os
import time
from functools import lru_cache

from app.config.loggers import app_logger as logger
from app.utils.exceptions import InfisicalConfigError

from infisical_sdk import InfisicalSDKClient
from dotenv import load_dotenv

load_dotenv()

_infisical_initialized = False


@lru_cache(maxsize=1)
def _get_infisical_client():
    """Get or create a cached Infisical client instance."""
    CLIENT_ID = os.getenv("INFISICAL_MACHINE_INDENTITY_CLIENT_ID")
    CLIENT_SECRET = os.getenv("INFISICAL_MACHINE_INDENTITY_CLIENT_SECRET")

    client = InfisicalSDKClient(
        host="https://app.infisical.com",
        cache_ttl=3600,
    )
    client.auth.universal_auth.login(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    return client


def inject_infisical_secrets():
    """Inject all Infisical secrets into environment variables once."""
    global _infisical_initialized

    if _infisical_initialized:
        return

    INFISICAL_PROJECT_ID = os.getenv("INFISICAL_PROJECT_ID")
    ENV = os.getenv("ENV", "production")
    CLIENT_ID = os.getenv("INFISICAL_MACHINE_INDENTITY_CLIENT_ID")
    CLIENT_SECRET = os.getenv("INFISICAL_MACHINE_INDENTITY_CLIENT_SECRET")

    is_production = ENV == "production"

    missing_configs = [
        (INFISICAL_PROJECT_ID, "INFISICAL_PROJECT_ID"),
        (CLIENT_ID, "INFISICAL_MACHINE_INDENTITY_CLIENT_ID"),
        (CLIENT_SECRET, "INFISICAL_MACHINE_INDENTITY_CLIENT_SECRET"),
    ]

    for config_value, config_name in missing_configs:
        if not config_value:
            message = (
                f"{config_name} is missing. This is required for secrets management."
            )
            if is_production:
                raise InfisicalConfigError(message)
            else:
                logger.warning(f"Development environment: {message}")
                return

    try:
        start_time = time.time()
        logger.info("Connecting to Infisical...")

        client = _get_infisical_client()
        logger.info(
            f"Infisical authentication completed in {time.time() - start_time:.3f}s"
        )

        secrets_start = time.time()
        secrets = client.secrets.list_secrets(
            project_id=INFISICAL_PROJECT_ID,
            environment_slug=ENV,
            secret_path="/",  # noqa: S105
            expand_secret_references=True,
            view_secret_value=True,
            recursive=False,
            include_imports=True,
        )
        logger.info(f"Infisical secrets fetched in {time.time() - secrets_start:.3f}s")

        injection_start = time.time()
        for secret in secrets.secrets:
            if os.environ.get(secret.secretKey) is None:
                os.environ[secret.secretKey] = secret.secretValue

        logger.info(
            f"Secrets injected into environment in {time.time() - injection_start:.3f}s"
        )
        _infisical_initialized = True

    except Exception as e:
        raise InfisicalConfigError(
            f"Failed to fetch secrets from Infisical: {e}"
        ) from e
