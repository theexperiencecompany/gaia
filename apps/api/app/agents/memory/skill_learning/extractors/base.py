"""
Base Extractor - Abstract base class for skill extraction strategies.
"""

from abc import ABC, abstractmethod
from typing import List

from langchain_core.messages import AnyMessage

from app.agents.memory.skill_learning.models import SkillExtractionResult


class BaseSkillExtractor(ABC):
    """Abstract base class for skill extraction strategies.

    Implementations:
    - LLMExtractor: Uses a cheap LLM to extract skills from conversations
    - ReflectionExtractor: Has the executing LLM document its own experience
    """

    @abstractmethod
    async def extract(
        self,
        messages: List[AnyMessage],
        agent_id: str,
        session_id: str | None = None,
    ) -> SkillExtractionResult:
        """Extract skills from a conversation.

        Args:
            messages: The conversation messages
            agent_id: The agent that executed the conversation
            session_id: Optional session ID for correlation

        Returns:
            SkillExtractionResult with extracted skills or skip reason
        """
        pass

    def should_extract(self, messages: List[AnyMessage]) -> tuple[bool, str]:
        """Check if the conversation is worth extracting skills from.

        Args:
            messages: The conversation messages

        Returns:
            Tuple of (should_extract, reason)
        """
        from langchain_core.messages import AIMessage

        if len(messages) < 4:
            return False, "Too few messages"

        # Count tool calls
        tool_calls = sum(
            len(msg.tool_calls)
            for msg in messages
            if isinstance(msg, AIMessage) and msg.tool_calls
        )

        if tool_calls < 2:
            return False, f"Only {tool_calls} tool calls - too simple"

        # Check for failure indicators in last AI message
        last_ai_msg = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                last_ai_msg = msg
                break

        if last_ai_msg:
            content_lower = str(last_ai_msg.content).lower()
            failure_words = ["sorry", "couldn't", "unable", "failed", "error", "cannot"]
            success_words = ["fixed", "resolved", "done", "completed", "success"]

            if any(word in content_lower for word in failure_words):
                if not any(word in content_lower for word in success_words):
                    return False, "Task appears to have failed"

        return True, "OK"
