"""Subagent identity model.

A `Subagent` is the canonical handle for a delegated agent: an OAuth
integration's subagent_config, or a built-in subagent registered in
`agents/core/subagents/builtin_subagents.py`.

Lookup keys are `id` and `short_name` (user-facing). The `config.agent_name`
field lives in a separate key space — that's the name registered with
`providers.aget(agent_name)` in the lazy provider system.
"""

from dataclasses import dataclass
from typing import Literal, Optional

from app.models.mcp_config import MCPConfig, SubAgentConfig


@dataclass(frozen=True, slots=True)
class Subagent:
    id: str
    name: str
    provider: str
    managed_by: Literal["self", "composio", "mcp", "internal"]
    config: SubAgentConfig
    short_name: Optional[str] = None
    mcp_config: Optional[MCPConfig] = None
