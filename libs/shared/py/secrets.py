"""
Infisical secrets management for GAIA applications.

Infisical streamlines environment variable sharing within the GAIA team for
production and staging deployments. Not required for self-hosting or
contributor development - use local .env files instead.

Local environment variables take precedence over Infisical secrets.

Resolution:
- All machine-identity vars set -> fetch remote secrets
- None set in dev -> skip (local .env only); in prod -> raise
- Partially set -> warn in dev, raise in prod
"""

import os
import time

from shared.py.wide_events import log


class InfisicalConfigError(Exception):
    """Raised when Infisical configuration is missing or invalid."""


_INFISICAL_VARS = (
    "INFISICAL_PROJECT_ID",
    "INFISICAL_MACHINE_IDENTITY_CLIENT_ID",
    "INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET",
)


def inject_infisical_secrets() -> None:
    """
    Load secrets from Infisical and inject into environment.

    Authenticates with a machine identity (Universal Auth) via
    INFISICAL_PROJECT_ID, INFISICAL_MACHINE_IDENTITY_CLIENT_ID and
    INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET.

    ENV doubles as the Infisical environment slug (development/staging/
    production).
    """
    env = os.getenv("ENV", "production")
    is_production = env == "production"

    present = [name for name in _INFISICAL_VARS if os.getenv(name)]
    missing = [name for name in _INFISICAL_VARS if not os.getenv(name)]

    if not present:
        if is_production:
            raise InfisicalConfigError(
                f"Infisical is required in production. Missing: {', '.join(missing)}"
            )
        log.info("Infisical skipped: no config vars set (using local .env only)")
        return

    if missing:
        message = (
            f"Incomplete Infisical config: missing {', '.join(missing)} "
            f"(found {', '.join(present)})"
        )
        if is_production:
            raise InfisicalConfigError(message)
        log.warning(message)
        return

    project_id = os.environ["INFISICAL_PROJECT_ID"]
    client_id = os.environ["INFISICAL_MACHINE_IDENTITY_CLIENT_ID"]
    client_secret = os.environ["INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET"]

    try:
        from infisical_sdk import InfisicalSDKClient  # noqa: PLC0415 -- optional dep, guarded below

        start_time = time.time()
        log.info("Connecting to Infisical...")

        client = InfisicalSDKClient(
            host="https://app.infisical.com",
            cache_ttl=3600,
        )
        client.auth.universal_auth.login(
            client_id=client_id,
            client_secret=client_secret,
        )
        log.info(f"Infisical authentication completed in {time.time() - start_time:.3f}s")

        secrets_start = time.time()
        secrets = client.secrets.list_secrets(
            project_id=project_id,
            environment_slug=env,
            secret_path="/",  # nosec B106 - Infisical folder path, not a credential
            expand_secret_references=True,
            view_secret_value=True,
            recursive=False,
            include_imports=True,
        )
        log.info(f"Infisical secrets fetched in {time.time() - secrets_start:.3f}s")

        injection_start = time.time()

        # Local env vars take precedence over Infisical
        for secret in secrets.secrets:
            if os.environ.get(secret.secretKey) is None:
                os.environ[secret.secretKey] = secret.secretValue

        log.info(f"Secrets injected into environment in {time.time() - injection_start:.3f}s")

    except Exception as e:
        raise InfisicalConfigError(f"Failed to fetch secrets from Infisical: {e}") from e


__all__ = [
    "inject_infisical_secrets",
    "InfisicalConfigError",
]
