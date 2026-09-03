"""One uniform way to connect an integration, whatever backs it.

Connecting used to be an ``if managed_by == ...`` chain, written out twice —
once in the ``POST /connect/{id}`` endpoint and once in
``initiate_integration_connection`` — with a different call signature per
branch. Two copies of a five-way dispatch is how a transport ends up wired into
one entry point and not the other (the login-free connect-link path already
supported fewer transports than the endpoint did).

A provider normalises the differences behind one call. Adding a transport is a
new module plus a registry entry, and it is reachable from every entry point at
once by construction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from app.models.integration_provider import ManagedBy
from app.schemas.integrations.responses import ConnectIntegrationResponse
from app.services.integrations.integration_resolver import ResolvedIntegration


@dataclass(frozen=True)
class ConnectContext:
    """Everything any transport needs to start or advance a connection.

    A single context rather than per-transport signatures: the endpoint should
    not have to know that Composio wants a provider slug while a CLI wants a
    pasted secret.
    """

    user_id: str
    integration_id: str
    resolved: ResolvedIntegration
    redirect_path: str
    # Only the self-managed (Google) flow uses this, as an OAuth login hint.
    user_email: str = ""
    # A secret the user pasted: an MCP bearer token, or a CLI's access token.
    # One field because it is one product concept — "the thing you pasted into
    # the connect dialog" — and the transport decides what to do with it.
    secret: str | None = None

    @property
    def provider_slug(self) -> str | None:
        """The upstream provider name, for transports keyed on it."""
        platform = self.resolved.platform_integration
        return platform.provider if platform else None


class IntegrationProvider(ABC):
    """Adapter for one integration transport."""

    managed_by: ClassVar[ManagedBy]

    @abstractmethod
    async def connect(self, ctx: ConnectContext) -> ConnectIntegrationResponse:
        """Start or advance a connection, and report where it stands.

        Implementations must be safe to call more than once for the same
        ``(user, integration)``: the CLI transport is polled by the client, and
        a user can double-click Connect on any of them.
        """

    @abstractmethod
    async def disconnect(self, user_id: str, resolved: ResolvedIntegration) -> None:
        """Undo a connection: revoke upstream, and drop what GAIA stored.

        The mirror of :meth:`connect`, and on the same interface for the same
        reason: a transport that is reachable from one and not the other is
        exactly the drift the registry exists to prevent.
        """

    def error(self, ctx: ConnectContext, message: str) -> ConnectIntegrationResponse:
        """A terminal failure in this transport's connect flow."""
        return ConnectIntegrationResponse(
            status="error",
            integration_id=ctx.integration_id,
            name=ctx.resolved.name,
            error=message,
        )


_PROVIDERS: dict[ManagedBy, IntegrationProvider] = {}


def register_provider(provider: IntegrationProvider) -> None:
    """Register a transport. Called once per module at import time."""
    _PROVIDERS[provider.managed_by] = provider


def get_provider(managed_by: ManagedBy) -> IntegrationProvider | None:
    """The transport for ``managed_by``, or ``None`` if it cannot be connected.

    ``internal`` integrations legitimately land here as ``None``: they are
    always available and have nothing to connect.
    """
    return _PROVIDERS.get(managed_by)
