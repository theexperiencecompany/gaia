"""
Infisical secrets management for GAIA applications.

Infisical streamlines environment variable sharing within the GAIA team for
production and staging deployments. Not required for self-hosting or
contributor development - use local .env files instead.

Local environment variables take precedence over Infisical secrets.
"""

import os
import time

from shared.py.logging import get_contextual_logger

logger = get_contextual_logger("secrets")


class InfisicalConfigError(Exception):
    """Raised when Infisical configuration is missing or invalid."""


def inject_infisical_secrets():
    """
    Load secrets from Infisical and inject into environment.

    Required environment variables:
    - INFISICAL_TOKEN
    - INFISICAL_PROJECT_ID
    - INFISICAL_MACHINE_IDENTITY_CLIENT_ID
    - INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET

    In development, missing Infisical config logs a warning and returns.
    In production, raises InfisicalConfigError.
    """
    INFISICAL_TOKEN = os.getenv("INFISICAL_TOKEN")
    INFISICAL_PROJECT_ID = os.getenv("INFISICAL_PROJECT_ID")
    ENV = os.getenv("ENV", "production")
    CLIENT_ID = os.getenv("INFISICAL_MACHINE_IDENTITY_CLIENT_ID")
    CLIENT_SECRET = os.getenv("INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET")

    is_production = ENV == "production"

    missing_configs = [
        (INFISICAL_TOKEN, "INFISICAL_TOKEN"),
        (INFISICAL_PROJECT_ID, "INFISICAL_PROJECT_ID"),
        (CLIENT_ID, "INFISICAL_MACHINE_IDENTITY_CLIENT_ID"),
        (CLIENT_SECRET, "INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET"),
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
        from infisical_sdk import InfisicalSDKClient

        start_time = time.time()
        logger.info("Connecting to Infisical...")

        client = InfisicalSDKClient(
            host="https://app.infisical.com",
            cache_ttl=3600,
        )
        client.auth.universal_auth.login(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
        )
        logger.info(
            f"Infisical authentication completed in {time.time() - start_time:.3f}s"
        )

        secrets_start = time.time()
        secrets = client.secrets.list_secrets(
            project_id=INFISICAL_PROJECT_ID,
            environment_slug=ENV,
            secret_path="/",
            expand_secret_references=True,
            view_secret_value=True,
            recursive=False,
            include_imports=True,
        )
        logger.info(f"Infisical secrets fetched in {time.time() - secrets_start:.3f}s")

        injection_start = time.time()

        # Local env vars take precedence over Infisical
        for secret in secrets.secrets:
            if os.environ.get(secret.secretKey) is None:
                os.environ[secret.secretKey] = secret.secretValue

        logger.info(
            f"Secrets injected into environment in {time.time() - injection_start:.3f}s"
        )

    except Exception as e:
        raise InfisicalConfigError(
            f"Failed to fetch secrets from Infisical: {e}"
        ) from e


__all__ = [
    "inject_infisical_secrets",
    "InfisicalConfigError",
]
