"""Describing an integration to be created, independently of how it is backed.

Creating an integration used to mean exactly one thing — point GAIA at an MCP
server URL — so the request shape, the validation and the creation path were all
MCP-shaped and fused together. A second transport (a CLI) needs the same
lifecycle (validate, create the catalog document, attach it to the user, verify
it actually works) with entirely different specifics.

A blueprint is the caller's intent; an author turns one kind of blueprint into a
real integration. The caller — today a chat tool, tomorrow an endpoint — states
what it wants and never branches on transport.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, Field

from app.models.integration_models import Integration
from app.models.integration_provider import ManagedBy


class BlueprintBase(BaseModel):
    """Fields every integration needs regardless of what backs it."""

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    category: str = Field(default="custom", max_length=50)


class McpBlueprint(BlueprintBase):
    """An integration backed by an MCP server."""

    kind: Literal["mcp"] = "mcp"
    server_url: str
    requires_auth: bool = False
    auth_type: Literal["none", "oauth", "bearer"] | None = None
    # A bearer token the user supplied up front, when they already have one.
    bearer_token: str | None = None


class CliBlueprint(BlueprintBase):
    """An integration backed by a real command-line tool."""

    kind: Literal["cli"] = "cli"
    command: str
    install_command: str
    capabilities: list[str] = Field(default_factory=list)
    auth_kind: Literal["none", "device", "token"] = "none"
    login_command: str | None = None
    verify_command: str
    logout_command: str | None = None
    token_env: str | None = None
    token_label: str | None = None
    token_help_url: str | None = None


IntegrationBlueprint = Annotated[McpBlueprint | CliBlueprint, Field(discriminator="kind")]


@dataclass(frozen=True)
class AuthoredIntegration:
    """The created integration, plus whether it is usable yet.

    ``needs_connection`` is what the caller tells the user next: an MCP server
    with no auth is ready immediately, while a CLI with a device login still
    needs them to approve something.
    """

    integration: Integration
    needs_connection: bool
    # Free-text, user-facing: what to do next, or what could not be verified.
    note: str | None = None


class IntegrationAuthor(ABC):
    """Turns one kind of blueprint into a stored, attached integration."""

    kind: ClassVar[str]
    managed_by: ClassVar[ManagedBy]

    @abstractmethod
    async def create(self, user_id: str, blueprint: IntegrationBlueprint) -> AuthoredIntegration:
        """Validate, persist, and attach the integration to the user."""


_AUTHORS: dict[str, IntegrationAuthor] = {}


def register_author(author: IntegrationAuthor) -> None:
    _AUTHORS[author.kind] = author


def get_author(kind: str) -> IntegrationAuthor | None:
    return _AUTHORS.get(kind)
