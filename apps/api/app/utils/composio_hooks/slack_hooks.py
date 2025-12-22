"""
Slack-specific hooks using the enhanced decorator system.

These hooks implement schema modifiers for customizing tool descriptions and defaults.
"""

from composio.types import Tool

from .registry import register_schema_modifier

# ====================== SCHEMA MODIFIERS ======================
# These modifiers customize tool schemas before they are seen by agents


@register_schema_modifier(tools=["SLACK_SEARCH_MESSAGES", "SLACK_SEARCH_ALL"])
def slack_search_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """
    Set sensible defaults for Slack search tools.

    - sort: default to "timestamp" (chronological, not relevance)
    - sort_dir: default to "desc" (newest first)
    - count: default to 20 (reasonable number of results)
    - Add guidance about using recent results first
    """
    props = schema.input_parameters.get("properties", {})

    # Set sort default to timestamp (chronological order)
    if "sort" in props:
        props["sort"]["default"] = "timestamp"

    # Set sort_dir default to desc (newest first)
    if "sort_dir" in props:
        props["sort_dir"]["default"] = "desc"

    # Set count default to 20 for reasonable results
    if "count" in props:
        props["count"]["default"] = 20

    # Add search guidance to description
    search_guidance = (
        "\n\n⚠️ IMPORTANT: Search returns messages sorted by NEWEST FIRST by default. "
        "When looking for recent conversations, use date modifiers like "
        "`after:YYYY-MM-DD` to narrow results. "
        "For finding specific discussions, combine filters: "
        "`from:@user in:#channel after:2024-01-01`"
    )
    schema.description += search_guidance

    return schema
