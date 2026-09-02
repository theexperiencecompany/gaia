"""Creating a CLI-backed integration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar
import uuid

from pydantic import ValidationError

from app.constants.log_tags import LogTag
from app.db.repositories.integrations import integration_repository
from app.models.cli_config import CliAuthSpec, CliConfig
from app.models.integration_models import Integration, IntegrationTool
from app.models.integration_provider import ManagedBy
from app.services.integrations.authoring.base import (
    AuthoredIntegration,
    CliBlueprint,
    IntegrationAuthor,
    IntegrationBlueprint,
    register_author,
)
from app.services.integrations.user_integrations import add_user_integration
from shared.py.wide_events import log


class CliIntegrationAuthor(IntegrationAuthor):
    """Stores a CLI integration so the connect flow can take it from there.

    Deliberately does NOT install or run the CLI here. Creation is a catalog
    write and must stay fast and side-effect-free in the user's sandbox; the
    first real install happens on connect, where there is a UI showing progress
    and somewhere sensible to report a failure.
    """

    kind: ClassVar[str] = "cli"
    managed_by: ClassVar[ManagedBy] = "cli"

    async def create(self, user_id: str, blueprint: IntegrationBlueprint) -> AuthoredIntegration:
        if not isinstance(blueprint, CliBlueprint):  # pragma: no cover - dispatch guarantees this
            raise TypeError(f"{type(self).__name__} cannot author a {blueprint.kind!r} blueprint")

        try:
            cli_config = CliConfig(
                command=blueprint.command,
                install_command=blueprint.install_command,
                capabilities=blueprint.capabilities,
                auth=CliAuthSpec(
                    kind=blueprint.auth_kind,
                    login_command=blueprint.login_command,
                    verify_command=blueprint.verify_command,
                    logout_command=blueprint.logout_command,
                    token_env=blueprint.token_env,
                    token_label=blueprint.token_label,
                    token_help_url=blueprint.token_help_url,
                ),
            )
        except ValidationError as e:
            # The blueprint came from an LLM that read a CLI's help text, so an
            # incoherent auth spec (device without a login command, token
            # without a variable name) is the expected failure. Surface exactly
            # what is wrong so it can fix it and retry.
            raise ValueError(f"Invalid CLI configuration: {e}") from e

        integration_id = str(uuid.uuid4())
        integration = Integration(
            integration_id=integration_id,
            name=blueprint.name,
            description=blueprint.description,
            category=blueprint.category,
            managed_by=self.managed_by,
            source="custom",
            is_public=False,
            created_by=user_id,
            display_priority=0,
            is_featured=False,
            cli_config=cli_config,
            # The capabilities double as the integration's displayed tool list:
            # they are what this integration can do, which is exactly what the
            # tool list means to a user, and it is what publishing validates.
            tools=[IntegrationTool(name=capability) for capability in cli_config.capabilities],
            requires_auth=cli_config.auth.kind != "none",
            created_at=datetime.now(UTC),
            icon_url=None,
            published_at=None,
            clone_count=0,
        )

        await integration_repository.create(integration)
        try:
            await add_user_integration(user_id, integration_id, initial_status="created")
        except Exception:
            # Leaving a catalog row nobody owns would surface as a ghost
            # integration in the marketplace, so undo it.
            log.error(
                f"{LogTag.INTEGRATION} Failed to attach authored CLI integration, rolling back",
                integration_id=integration_id,
                user_id=user_id,
            )
            await integration_repository.delete(integration_id)
            raise

        needs_connection = cli_config.auth.kind != "none"
        return AuthoredIntegration(
            integration=integration,
            needs_connection=True,
            note=(
                f"Connect it to install {cli_config.command} and sign in."
                if needs_connection
                else f"Connect it once to install {cli_config.command}."
            ),
        )


register_author(CliIntegrationAuthor())
