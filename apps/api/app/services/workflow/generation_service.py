"""Workflow generation service for LLM-based step creation."""

from typing import List

from app.agents.llm.client import init_llm
from app.agents.prompts.trigger_prompts import generate_trigger_context
from app.agents.templates.workflow_template import (
    WORKFLOW_GENERATION_TEMPLATE,
    workflow_parser,
)
from app.config.loggers import general_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.models.workflow_models import GeneratedStep


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
        description: str, title: str, trigger_config=None
    ) -> list:
        """Generate workflow steps using LLM with Pydantic parser."""
        try:
            logger.info(f"[WorkflowGen] ========== START: {title} ==========")

            # Import here to avoid circular dependency
            from app.agents.tools.core.registry import get_tool_registry

            logger.info("[WorkflowGen] Getting tool registry...")
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

            logger.info(f"[WorkflowGen] Categories: {len(category_names)}")

            trigger_context = generate_trigger_context(trigger_config)

            llm = init_llm()

            logger.info("[WorkflowGen] Formatting prompt...")
            # format_instructions is pre-filled via partial_variables
            formatted_prompt = WORKFLOW_GENERATION_TEMPLATE.format(
                description=description,
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
