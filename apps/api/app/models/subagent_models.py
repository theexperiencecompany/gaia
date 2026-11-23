"""Subagent identity model.

A `Subagent` is the canonical handle for an integration the executor activates:
an OAuth integration's subagent_config, or a built-in one registered in
`agents/core/subagents/builtin_subagents.py`.

Lookup keys are `id` and `short_name` (user-facing). The `config.agent_name`
field lives in a separate key space: the skill catalog and activation key on it.
"""

from dataclasses import dataclass
from typing import Literal

from app.models.mcp_config import MCPConfig, SubAgentConfig


@dataclass(frozen=True, slots=True)
class Subagent:
    id: str
    name: str
    provider: str
    managed_by: Literal["self", "composio", "mcp", "internal"]
    config: SubAgentConfig
    short_name: str | None = None
    mcp_config: MCPConfig | None = None
    # False when the integration is listed but cannot be reached (dead endpoint).
    available: bool = True
