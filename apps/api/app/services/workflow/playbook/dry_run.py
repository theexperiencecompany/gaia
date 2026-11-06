"""A replay that only reads: allowlisted read tools run for real, every other step is only described.

What a dry run is for: proving a playbook resolves and replays against one real
user's data without acting for them. A step whose tool (seen through execute)
is not on the allowlist never reaches the tool; its result is a note of what
it would have called, so later steps and the narration still run over it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import json

from app.agents.tools.execute.unwrap import unwrap_execute_call

#: Tools that only read. A tool joins only after reading its code: a fetch that
#: offloads to storage or marks mail read is a write and stays off.
DRY_RUN_READ_TOOLS = frozenset(
    {
        "GOOGLECALENDAR_CUSTOM_GET_EVENT",
        "GOOGLECALENDAR_CUSTOM_FETCH_EVENTS",
        "GOOGLECALENDAR_EVENTS_LIST",
        "search_memory",
        "web_search_tool",
    }
)


@dataclass(frozen=True, slots=True)
class DryRun:
    """The tools a dry run lets through; everything else is described, not called."""

    reads: frozenset[str] = DRY_RUN_READ_TOOLS

    def runs(self, tool_name: str, args: Mapping[str, object]) -> bool:
        """Whether a step's call may really run."""
        real_name, _ = unwrap_execute_call(tool_name, dict(args))
        return real_name in self.reads

    def would_call(self, tool_name: str, args: Mapping[str, object]) -> str:
        """Return what a held-back call answers with: the call it would have made, as JSON."""
        real_name, real_args = unwrap_execute_call(tool_name, dict(args))
        return json.dumps({"dry_run": f"would call {real_name}", "args": real_args}, default=str)
