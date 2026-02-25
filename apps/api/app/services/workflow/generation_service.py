"""Workflow generation service for LLM-based step creation."""

from typing import List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser

from app.agents.llm.client import init_llm
from app.agents.prompts.trigger_prompts import generate_trigger_context
from app.agents.prompts.workflow_prompts import (
    WORKFLOW_PROMPT_GENERATION_SYSTEM,
    WORKFLOW_PROMPT_GENERATION_TEMPLATE,
)
from app.agents.templates.workflow_template import (
    WORKFLOW_GENERATION_TEMPLATE,
    workflow_parser,
)
from app.config.loggers import general_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.models.workflow_models import (
    GeneratedPromptOutput,
    GeneratedStep,
    SuggestedTrigger,
)

prompt_output_parser = PydanticOutputParser(pydantic_object=GeneratedPromptOutput)


def _build_trigger_hint(trigger_config: Optional[dict]) -> str:
    """Build a minimal, human-readable trigger hint for the LLM.

    We intentionally omit raw cron/timezone/next_run so the LLM cannot
    leak scheduling details into the instructions prose.
    """
    if not trigger_config:
        return (
            "No trigger selected yet — suggest the most appropriate trigger "
            "type based on the user's intent."
        )

    trigger_type = trigger_config.get("type", "manual")

    if trigger_type == "schedule":
        cron = trigger_config.get("cron_expression", "")
        hint = "User has selected a scheduled trigger"
        if cron:
            hint += f" (current cron: {cron})"
        hint += ". Suggest a cron expression that matches the described cadence."
        return hint
    if trigger_type == "manual":
        return (
            "User has selected a manual trigger. Respect this unless "
            "the instructions clearly imply a recurring schedule."
        )
    # Integration triggers
    trigger_name = trigger_config.get("trigger_name", "")
    if trigger_name:
        return f"User has selected an integration trigger ({trigger_name})."
    return f"User has selected trigger type: {trigger_type}."


def _build_available_triggers() -> str:
    """Build a compact list of available integration triggers for the LLM."""
    lines: List[str] = []
    for integration in OAUTH_INTEGRATIONS:
        for tc in integration.associated_triggers:
            schema = tc.workflow_trigger_schema
            if schema:
                desc = f" — {schema.description}" if schema.description else ""
                lines.append(
                    f"- {schema.slug}: {schema.name} ({integration.name}){desc}"
                )
    if not lines:
        return ""
    return (
        "Available integration triggers (use the slug for trigger_name):\n"
        + "\n".join(lines)
    )


def enrich_steps(generated_steps: List[GeneratedStep]) -> List[dict]:
    """Convert minimal generated steps to full step schema with id."""
    enriched = []
    for i, step in enumerate(generated_steps):
        enriched.append(
            {
                "id": f"step_{i}",
                "title": step.title,
                "category": step.category,
                "description": step.description,
            }
        )
    return enriched


class WorkflowGenerationService:
    """Service for generating workflow steps using LLM."""

    @staticmethod
    async def generate_steps_with_llm(
        prompt: str, title: str, trigger_config=None, description: str | None = None
    ) -> list:
        """Generate workflow steps using LLM with Pydantic parser."""
        try:
            logger.info(f"[WorkflowGen] ========== START: {title} ==========")

            logger.info("[WorkflowGen] Getting tool registry...")
            # Inline import required: top-level causes a circular import via
            # registry → workflow_tool → services.workflow → generation_service
            from app.agents.tools.core.registry import get_tool_registry

            tool_registry = await get_tool_registry()

            tools_with_categories = []
            category_names = []
            categories = tool_registry.get_all_category_objects()
            for category in categories.keys():
                category_names.append(category)
                category_tools = categories[category].get_tool_objects()
                tool_names = [
                    tool.name if hasattr(tool, "name") else str(tool)
                    for tool in category_tools
                ]
                tools_with_categories.append(f"{category}: {', '.join(tool_names)}")

            # Add subagent capabilities
            for integration in OAUTH_INTEGRATIONS:
                if (
                    integration.subagent_config
                    and integration.subagent_config.has_subagent
                ):
                    cfg = integration.subagent_config
                    category_names.append(integration.id)
                    tools_with_categories.append(
                        f"{integration.id} (subagent): {cfg.capabilities}"
                    )

            for tool in tool_registry.get_core_tools():
                tool_name = tool.name if hasattr(tool, "name") else str(tool)
                tools_with_categories.append(f"Always Available: {tool_name}")

            # gaia is always a valid category — for pure LLM reasoning steps
            # (summarize, draft, classify, generate, analyze) with no external tool call
            category_names.append("gaia")
            tools_with_categories.append(
                "gaia: GAIA reasoning — summarize content, draft text, classify items, "
                "generate outlines, extract key points, write briefs. No external tool call."
            )

            logger.info(f"[WorkflowGen] Categories: {len(category_names)}")

            trigger_context = generate_trigger_context(trigger_config)

            llm = init_llm()

            logger.info("[WorkflowGen] Formatting prompt...")
            prompt_context = prompt
            if description:
                prompt_context = (
                    f"{prompt}\n\n"
                    f"Short display summary for additional context: {description}"
                )
            # format_instructions is pre-filled via partial_variables
            formatted_prompt = WORKFLOW_GENERATION_TEMPLATE.format(
                description=prompt_context,
                title=title,
                trigger_context=trigger_context,
                tools="\n".join(tools_with_categories),
                categories=", ".join(category_names),
            )
            logger.info(f"[WorkflowGen] Prompt: {len(formatted_prompt)} chars")

            logger.info("[WorkflowGen] === CALLING LLM ===")
            llm_response = await llm.ainvoke(formatted_prompt)
            logger.info("[WorkflowGen] === LLM RESPONDED ===")

            # Parse response
            response_content = getattr(llm_response, "content", str(llm_response))
            logger.info(f"[WorkflowGen] Response: {len(response_content)} chars")
            logger.debug(f"[WorkflowGen] Full response:\n{response_content}")

            logger.info("[WorkflowGen] === PARSING ===")
            result = workflow_parser.parse(response_content)
            logger.info(f"[WorkflowGen] === SUCCESS: {len(result.steps)} steps ===")

            # Enrich with id
            steps_data = enrich_steps(result.steps)

            logger.info(
                f"[WorkflowGen] ========== DONE: {len(steps_data)} steps =========="
            )
            return steps_data

        except Exception as e:
            logger.error(
                f"[WorkflowGen] ========== FAILED: {e} ==========", exc_info=True
            )
            return []

    @staticmethod
    async def generate_workflow_prompt(
        title: Optional[str] = None,
        description: Optional[str] = None,
        trigger_config: Optional[dict] = None,
        existing_prompt: Optional[str] = None,
    ) -> dict:
        """Generate or improve workflow instructions using LLM.

        Returns a dict with keys: prompt, suggested_trigger (optional).
        """
        trigger_hint = _build_trigger_hint(trigger_config)
        available_triggers = _build_available_triggers()

        llm = init_llm(use_free=True)

        formatted = WORKFLOW_PROMPT_GENERATION_TEMPLATE.format(
            title_section=f"Title: {title}\n" if title else "",
            description_section=f"Description: {description}" if description else "",
            trigger_hint=trigger_hint,
            available_triggers=available_triggers,
            existing_section=(
                f"Existing instructions to improve:\n{existing_prompt}"
                if existing_prompt
                else ""
            ),
            mode_instruction=(
                "Improve these instructions — keep the user's intent, add specificity, "
                "edge case handling, and output details."
                if existing_prompt
                else "Generate comprehensive workflow instructions from scratch."
            ),
            format_instructions=prompt_output_parser.get_format_instructions(),
        )

        messages = [
            SystemMessage(content=WORKFLOW_PROMPT_GENERATION_SYSTEM),
            HumanMessage(content=formatted),
        ]

        response = await llm.ainvoke(messages)
        response_content = getattr(response, "content", str(response)).strip()

        result = prompt_output_parser.parse(response_content)

        suggested: Optional[SuggestedTrigger] = None
        if result.trigger_type in ("manual", "schedule", "integration"):
            suggested = SuggestedTrigger(
                type=result.trigger_type,
                cron_expression=result.cron_expression,
                trigger_name=result.trigger_name,
            )

        return {"prompt": result.instructions, "suggested_trigger": suggested}
