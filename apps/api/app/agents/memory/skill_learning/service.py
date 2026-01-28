"""
Skill Learning Service - Main orchestration for skill extraction and storage.

This service:
1. Runs both extractors (LLM + Reflection) in parallel
2. Stores results via MongoDB storage backend
3. Provides search_skills() for retrieval

Replaces the mem0-based skill extraction with our custom solution.
User memory still uses mem0 via the separate code path.
"""

import asyncio
from typing import List, Optional

from langchain_core.messages import AnyMessage
from langchain_openai import ChatOpenAI

from app.agents.memory.skill_learning.extractors.llm_extractor import LLMSkillExtractor
from app.agents.memory.skill_learning.extractors.reflection import ReflectionExtractor
from app.agents.memory.skill_learning.models import Skill, SkillSearchResult
from app.agents.memory.skill_learning.storage import (
    search_skills as storage_search_skills,
    store_skills_batch,
)
from app.config.loggers import llm_logger as logger


class SkillLearningService:
    """Orchestrates skill extraction and storage.

    Runs two extraction strategies in parallel:
    1. LLM Extraction - Cheap model analyzes the conversation
    2. Self-Reflection - Executing LLM documents its experience

    Both strategies run as background tasks (fire-and-forget).
    """

    def __init__(
        self,
        enable_llm_extraction: bool = True,
        enable_reflection: bool = True,
    ):
        """Initialize the skill learning service.

        Args:
            enable_llm_extraction: Enable cheap LLM extraction
            enable_reflection: Enable self-reflection extraction
        """
        self.enable_llm_extraction = enable_llm_extraction
        self.enable_reflection = enable_reflection

        # Extractors are created lazily
        self._llm_extractor: Optional[LLMSkillExtractor] = None
        self._reflection_extractor: Optional[ReflectionExtractor] = None

    def _get_llm_extractor(self) -> LLMSkillExtractor:
        """Get or create the LLM extractor."""
        if self._llm_extractor is None:
            self._llm_extractor = LLMSkillExtractor()
        return self._llm_extractor

    def _get_reflection_extractor(
        self, llm: Optional[ChatOpenAI] = None
    ) -> ReflectionExtractor:
        """Get or create the reflection extractor."""
        if self._reflection_extractor is None:
            self._reflection_extractor = ReflectionExtractor(llm=llm)
        elif llm is not None:
            self._reflection_extractor.set_llm(llm)
        return self._reflection_extractor

    async def learn_from_conversation(
        self,
        messages: List[AnyMessage],
        agent_id: str,
        session_id: Optional[str] = None,
        executing_llm: Optional[ChatOpenAI] = None,
    ) -> None:
        """Extract and store skills from a conversation.

        Runs enabled extractors in parallel and stores all extracted skills.
        This is designed to be called as a fire-and-forget background task.

        Args:
            messages: The conversation messages
            agent_id: The agent that executed (e.g., "twitter_agent")
            session_id: Optional session ID for correlation
            executing_llm: Optional LLM instance for reflection (best results)
        """
        if not agent_id:
            logger.warning("agent_id required for skill learning")
            return

        if not messages:
            return

        # Collect extraction tasks with labels
        extraction_tasks = []
        task_labels = []

        if self.enable_llm_extraction:
            llm_extractor = self._get_llm_extractor()
            extraction_tasks.append(
                llm_extractor.extract(messages, agent_id, session_id)
            )
            task_labels.append("LLM")

        if self.enable_reflection:
            reflection_extractor = self._get_reflection_extractor(executing_llm)
            extraction_tasks.append(
                reflection_extractor.extract(messages, agent_id, session_id)
            )
            task_labels.append("Reflection")

        if not extraction_tasks:
            return

        # Run extractors in parallel
        try:
            results = await asyncio.gather(*extraction_tasks, return_exceptions=True)

            # Collect all successfully extracted skills with source tracking
            all_skills: List[Skill] = []
            skills_by_source: dict[str, int] = {}

            for i, result in enumerate(results):
                label = task_labels[i] if i < len(task_labels) else f"Task{i}"

                if isinstance(result, Exception):
                    logger.error(f"[{agent_id}] {label} extraction failed: {result}")
                    continue

                # Type guard: result is now guaranteed to be SkillExtractionResult
                if hasattr(result, "skills") and result.skills:
                    all_skills.extend(result.skills)
                    skills_by_source[label] = len(result.skills)
                    # Log each skill's trigger for visibility
                    for skill in result.skills:
                        logger.debug(
                            f"[{agent_id}] {label} extracted: {skill.trigger[:60]}..."
                        )
                elif hasattr(result, "skipped_reason") and result.skipped_reason:
                    logger.debug(
                        f"[{agent_id}] {label} skipped: {result.skipped_reason}"
                    )

            # Store all skills in batch
            if all_skills:
                stored_count = await store_skills_batch(all_skills)
                source_summary = ", ".join(
                    f"{k}={v}" for k, v in skills_by_source.items()
                )
                logger.info(
                    f"[{agent_id}] Learned {stored_count} skills ({source_summary})"
                )

        except Exception as e:
            logger.error(f"[{agent_id}] Skill learning failed: {e}")

    async def search_skills(
        self,
        query: str,
        agent_id: str,
        limit: int = 5,
    ) -> SkillSearchResult:
        """Search for relevant skills.

        Args:
            query: What the user is trying to do
            agent_id: Agent to search skills for
            limit: Maximum results to return

        Returns:
            SkillSearchResult with matching skills
        """
        return await storage_search_skills(
            query=query,
            agent_id=agent_id,
            limit=limit,
        )

    def format_skills_for_prompt(
        self,
        skills: List[Skill],
        agent_id: str,
    ) -> str:
        """Format skills for injection into system prompt.

        Args:
            skills: List of skills to format
            agent_id: Agent name for header

        Returns:
            Formatted string for prompt injection
        """
        if not skills:
            return ""

        lines = [
            f"\n## Learned Procedures ({agent_id}):",
            "Use these approaches if relevant:\n",
        ]

        for i, skill in enumerate(skills, 1):
            lines.append(f"### {i}. {skill.trigger}")
            lines.append(skill.procedure)
            if skill.tools_used:
                lines.append(f"Tools: {', '.join(skill.tools_used)}")
            if skill.success_criteria:
                lines.append(f"Success: {skill.success_criteria}")
            lines.append("")

        return "\n".join(lines)


# Global service instance (lazily initialized)
_service_instance: Optional[SkillLearningService] = None


def get_skill_learning_service() -> SkillLearningService:
    """Get the global skill learning service instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = SkillLearningService()
    return _service_instance


async def learn_skills(
    messages: List[AnyMessage],
    agent_id: str,
    session_id: Optional[str] = None,
    executing_llm: Optional[ChatOpenAI] = None,
) -> None:
    """Convenience function to learn skills from a conversation.

    This is the main entry point for skill learning.
    Runs extraction in the background (fire-and-forget pattern).

    Args:
        messages: The conversation messages
        agent_id: The agent that executed (e.g., "twitter_agent")
        session_id: Optional session ID for correlation
        executing_llm: Optional LLM for better reflection quality
    """
    service = get_skill_learning_service()
    await service.learn_from_conversation(
        messages=messages,
        agent_id=agent_id,
        session_id=session_id,
        executing_llm=executing_llm,
    )
