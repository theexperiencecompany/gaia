"""
Trigger context template for workflow generation.
Simple template that accepts raw trigger config data as JSON.
"""

import json
from typing import Any, Optional

TRIGGER_CONTEXT_TEMPLATE = """## TRIGGER CONTEXT:

**Trigger Configuration:**
{trigger_data}

**WORKFLOW DESIGN PRINCIPLES:**
- The LLM will have complete trigger context during execution
- Focus on EXTERNAL tool actions that work with the trigger data
- The LLM will intelligently extract info, understand context, and make decisions automatically
- Do NOT create steps for 'analyze trigger' or 'extract information' - the LLM does this inherently
- Consider what external actions should happen BASED ON the trigger context

**TRIGGER-SPECIFIC GUIDANCE:**
{trigger_specific_guidance}
"""


def generate_trigger_specific_guidance(trigger_config) -> str:
    """Generate specific guidance based on trigger type."""
    if not trigger_config:
        return "No specific trigger guidance - this is a manual workflow."

    # Get trigger type - handle both dict and object forms
    trigger_type = None
    if hasattr(trigger_config, "type"):
        trigger_type = trigger_config.type
    elif isinstance(trigger_config, dict):
        trigger_type = trigger_config.get("type")

    if trigger_type == "email":
        return """
**EMAIL TRIGGER - IMPORTANT:**
- The triggering email (sender, subject, content) is ALREADY AVAILABLE during execution
- DO NOT create steps to fetch, search, or retrieve the triggering email
- DO NOT use: fetch_gmail_messages, search_gmail_messages, get_email_thread for the trigger email
- FOCUS ON: Actions to take BASED ON the email content (reply, forward, create tasks, etc.)
- Example good steps: compose_email (reply), create_calendar_event (meeting), create_reminder (follow-up)
- The LLM will automatically understand the email content and extract relevant information
"""
    elif trigger_type == "calendar":
        return """
**CALENDAR TRIGGER - IMPORTANT:**
- The triggering calendar event details are ALREADY AVAILABLE during execution
- DO NOT create steps to fetch or search for the triggering event
- FOCUS ON: Actions to take BASED ON the event (notifications, preparations, follow-ups)
"""
    elif trigger_type == "schedule":
        return """
**SCHEDULED TRIGGER:**
- This workflow runs on a schedule (cron expression)
- Focus on periodic tasks and maintenance actions
- Consider what data needs to be gathered and what actions need to be taken regularly
"""
    else:
        trigger_type_str = str(trigger_type).upper() if trigger_type else "UNKNOWN"
        return f"""
**{trigger_type_str} TRIGGER:**
- Consider what data is provided by this trigger type
- Focus on actions that utilize the trigger context
- Avoid redundant data fetching steps
"""


def generate_trigger_context(trigger_config: Optional[Any] = None) -> str:
    """
    Generate trigger context for workflow prompts.

    Args:
        trigger_config: Trigger configuration object or dict

    Returns:
        Formatted trigger context string for workflow generation
    """
    if not trigger_config:
        return "No trigger configuration provided - this is a manual workflow."

    # Convert to dict first, then to JSON
    if hasattr(trigger_config, "model_dump"):
        config_dict = trigger_config.model_dump(mode="json")
    else:
        config_dict = trigger_config
    trigger_data = json.dumps(config_dict, indent=2)

    # Generate trigger-specific guidance
    trigger_specific_guidance = generate_trigger_specific_guidance(trigger_config)

    return TRIGGER_CONTEXT_TEMPLATE.format(
        trigger_data=trigger_data, trigger_specific_guidance=trigger_specific_guidance
    )
