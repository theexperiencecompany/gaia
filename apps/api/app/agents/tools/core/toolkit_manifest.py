"""
Toolkit manifests for Composio integration tools.

Each manifest captures the full dependency graph for a toolkit's custom tools:
  - Output fields: what keys the tool returns (undocumented in the tool itself)
  - Dependencies: which tools must run first to supply required inputs
  - Workflows: recommended call sequences for common tasks

Manifests are registered by CustomToolsRegistry.initialize() and consumed by
build_subagent_system_prompt() to inject structured tool context into each
subagent's system prompt — replacing fuzzy ChromaDB guessing with an explicit
dependency graph the agent can follow.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolOutputField:
    """A single key in a tool's return dict."""

    name: str
    type: str
    description: str


@dataclass
class ToolManifestEntry:
    """Complete dependency metadata for one custom tool in a toolkit."""

    description: str
    outputs: list[ToolOutputField]
    depends_on: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class ToolWorkflow:
    """A recommended call sequence for a common user-facing goal."""

    goal: str
    steps: list[str]
    note: str = ""


@dataclass
class ToolkitManifest:
    """
    Dependency graph for all custom tools in one integration toolkit.

    The toolkit name must match the key used in CustomToolsRegistry
    (e.g., 'linear', 'googlecalendar', 'gmail', 'microsoft_teams').
    """

    toolkit: str
    tools: dict[str, ToolManifestEntry]
    workflows: list[ToolWorkflow] = field(default_factory=list)


# Maps integration_id (used in subagent routing / oauth_config) to the
# toolkit name stored in this registry.  Only entries that differ are listed.
_INTEGRATION_TO_TOOLKIT: dict[str, str] = {
    "calendar": "googlecalendar",
    "google_tasks": "googletasks",
    "google_docs": "googledocs",
    "google_sheets": "googlesheets",
    "google_maps": "google_maps",
    "google_meet": "googlemeet",
    "teams": "microsoft_teams",
}


class ToolkitManifestRegistry:
    """Registry mapping toolkit names → ToolkitManifest instances."""

    def __init__(self) -> None:
        self._manifests: dict[str, ToolkitManifest] = {}

    def register(self, manifest: ToolkitManifest) -> None:
        self._manifests[manifest.toolkit.lower()] = manifest

    def get(self, toolkit: str) -> ToolkitManifest | None:
        return self._manifests.get(toolkit.lower())

    def get_by_integration_id(self, integration_id: str) -> ToolkitManifest | None:
        """Look up manifest by subagent integration_id, handling name mismatches."""
        toolkit = _INTEGRATION_TO_TOOLKIT.get(
            integration_id.lower(), integration_id.lower()
        )
        return self._manifests.get(toolkit)

    def format_for_prompt(self, toolkit: str) -> str:
        """Formatted dependency graph for injection into a system prompt."""
        manifest = self.get(toolkit)
        if not manifest:
            return ""
        return _format_manifest(manifest)

    def format_by_integration_id(self, integration_id: str) -> str:
        """format_for_prompt variant that accepts a subagent integration_id."""
        manifest = self.get_by_integration_id(integration_id)
        if not manifest:
            return ""
        return _format_manifest(manifest)


toolkit_manifest_registry = ToolkitManifestRegistry()


def _format_manifest(manifest: ToolkitManifest) -> str:
    lines: list[str] = [
        f"## {manifest.toolkit.upper()} — CUSTOM TOOL REFERENCE\n",
        "Call these tools directly in dependency order."
        " Do not rely on ChromaDB retrieval for this toolkit.\n",
    ]

    for tool_name, entry in manifest.tools.items():
        tag_str = f"  [{', '.join(entry.tags)}]" if entry.tags else ""
        lines.append(f"**{tool_name}**{tag_str}")
        lines.append(f"  {entry.description}")
        if entry.depends_on:
            lines.append(f"  ⚠ Requires first: {', '.join(entry.depends_on)}")
        if entry.outputs:
            out_str = ", ".join(f"{o.name} ({o.type})" for o in entry.outputs)
            lines.append(f"  Returns: {out_str}")
        lines.append("")

    if manifest.workflows:
        lines.append("**Workflows:**")
        for wf in manifest.workflows:
            lines.append(f"  {wf.goal}:")
            for step in wf.steps:
                lines.append(f"    {step}")
            if wf.note:
                lines.append(f"    Note: {wf.note}")
            lines.append("")

    return "\n".join(lines)
