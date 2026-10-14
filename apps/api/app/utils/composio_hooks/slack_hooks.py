"""
Slack-specific hooks using the enhanced decorator system.

These hooks implement schema modifiers for customizing tool descriptions and defaults.
"""

from composio.types import Tool

from app.models.integrations.composio_hooks import JsonSchemaNode

from .registry import register_schema_modifier

# The Slack search params this modifier defaults, by Composio's names for them.
_SORT_PARAM = "sort"
_SORT_DIR_PARAM = "sort_dir"
_COUNT_PARAM = "count"

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
    input_params = JsonSchemaNode.parse(schema.input_parameters)
    if input_params is None:
        return schema

    props = input_params.properties or {}

    # Set sort default to timestamp (chronological order)
    if (sort := props.get(_SORT_PARAM)) is not None:
        sort.default = "timestamp"

    # Set sort_dir default to desc (newest first)
    if (sort_dir := props.get(_SORT_DIR_PARAM)) is not None:
        sort_dir.default = "desc"

    # Set count default to 20 for reasonable results
    if (count := props.get(_COUNT_PARAM)) is not None:
        count.default = 20

    schema.input_parameters = input_params.as_schema()

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
