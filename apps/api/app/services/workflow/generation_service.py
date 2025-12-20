"""Workflow generation service for LLM-based step creation."""

import re
from typing import List

from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

from app.agents.llm.client import init_llm
from app.agents.prompts.trigger_prompts import generate_trigger_context
from app.agents.templates.workflow_template import WORKFLOW_GENERATION_TEMPLATE
from app.config.loggers import general_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS


class GeneratedStep(BaseModel):
    """Minimal schema for LLM-generated steps - only fields LLM should output."""

    title: str = Field(description="Human-readable step name")
    category: str = Field(description="Category for routing (gmail, github, etc)")
    description: str = Field(description="What this step accomplishes")


class GeneratedWorkflow(BaseModel):
    """Schema for LLM output - minimal fields only."""

    steps: List[GeneratedStep] = Field(description="List of workflow steps")


def extract_json_from_response(response: str) -> str:
    """Extract JSON from markdown code blocks if present."""
    # Try ```json or ``` blocks
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
    if match:
        return match.group(1).strip()
    return response.strip()


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
        """Generate workflow steps using LLM with structured output."""
        try:
            logger.info(f"[WorkflowGen] Starting generation for: {title}")

            # Use minimal schema for parsing - LLM only outputs title, category, description
            parser = PydanticOutputParser(pydantic_object=GeneratedWorkflow)

            # Import here to avoid circular dependency at module level
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

            # Add subagent capabilities for provider-specific categories
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

            logger.info(f"[WorkflowGen] Available categories: {category_names}")

            trigger_context = generate_trigger_context(trigger_config)

            # Initialize LLM
            llm = init_llm()

            # Format the prompt using the template
            formatted_prompt = WORKFLOW_GENERATION_TEMPLATE.format(
                description=description,
                title=title,
                trigger_context=trigger_context,
                tools="\n".join(tools_with_categories),
                categories=", ".join(category_names),
                format_instructions=parser.get_format_instructions(),
            )

            logger.info(
                f"[WorkflowGen] Prompt length: {len(formatted_prompt)} chars, calling LLM..."
            )

            # Generate workflow plan using LLM directly
            llm_response = await llm.ainvoke(formatted_prompt)

            # Extract content (handle different response types)
            response_content = getattr(llm_response, "content", str(llm_response))
            logger.info(
                f"[WorkflowGen] LLM response length: {len(response_content)} chars"
            )

            # Extract JSON from markdown code blocks if present
            json_content = extract_json_from_response(response_content)
            if json_content != response_content:
                logger.info("[WorkflowGen] Extracted JSON from markdown code block")

            # Parse with minimal schema
            result = parser.parse(json_content)
            logger.info(f"[WorkflowGen] Successfully parsed {len(result.steps)} steps")

            # Enrich with id/order (fields LLM doesn't generate)
            steps_data = enrich_steps(result.steps)

            logger.info(
                f"[WorkflowGen] Generated {len(steps_data)} workflow steps for: {title}"
            )
            return steps_data

        except Exception as e:
            logger.error(f"[WorkflowGen] Failed to generate steps: {e}", exc_info=True)
            return []
