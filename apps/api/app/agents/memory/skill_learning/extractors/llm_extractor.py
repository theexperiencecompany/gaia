"""
LLM-based Skill Extractor - Uses a cheap LLM to extract skills from conversations.

This approach:
1. Formats the conversation into a compact representation
2. Sends it to a cheap/fast LLM (e.g., gpt-4o-mini, gemini-flash)
3. Parses the JSON response into Skill objects
"""

import json
import time
from typing import Dict, List, Optional

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI

from app.agents.memory.skill_learning.extractors.base import BaseSkillExtractor
from app.agents.memory.skill_learning.models import (
    Skill,
    SkillExtractionResult,
    SkillType,
)
from app.agents.memory.skill_learning.prompts import LLM_EXTRACTION_PROMPT
from app.config.loggers import llm_logger as logger
from app.constants.llm import DEFAULT_OPENAI_MODEL_NAME


# Maximum characters for tool outputs in formatted conversation
MAX_TOOL_OUTPUT_SIZE = 200


class LLMSkillExtractor(BaseSkillExtractor):
    """Extracts skills from conversations using a cheap LLM.

    Uses a smaller/cheaper model to analyze conversations and extract
    reusable procedural skills. This is cost-effective for background
    processing where latency isn't critical.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_OPENAI_MODEL_NAME,
        temperature: float = 0.0,
    ):
        """Initialize the LLM extractor.

        Args:
            model_name: The model to use for extraction (default: gpt-4o-mini)
            temperature: Temperature for extraction (default: 0.0 for consistency)
        """
        self.model_name = model_name
        self.temperature = temperature
        self._llm: Optional[ChatOpenAI] = None

    def _get_llm(self) -> ChatOpenAI:
        """Get or create the LLM instance."""
        if self._llm is None:
            self._llm = ChatOpenAI(
                model=self.model_name,
                temperature=self.temperature,
            )
        return self._llm

    def _format_messages(self, messages: List[AnyMessage]) -> List[Dict[str, str]]:
        """Format messages into a compact representation for the LLM.

        Truncates large tool outputs while preserving conversation structure.
        """
        formatted = []

        for msg in messages:
            if isinstance(msg, SystemMessage):
                # Skip system messages - not relevant for skill extraction
                continue

            elif isinstance(msg, HumanMessage):
                content = self._extract_text_content(msg.content)
                if content:
                    formatted.append({"role": "user", "content": content})

            elif isinstance(msg, AIMessage):
                if msg.tool_calls:
                    for call in msg.tool_calls:
                        args_str = str(call.get("args", {}))
                        if len(args_str) > 150:
                            args_str = args_str[:150] + "..."
                        formatted.append(
                            {
                                "role": "assistant",
                                "content": f"[TOOL: {call['name']}({args_str})]",
                            }
                        )
                elif msg.content:
                    formatted.append({"role": "assistant", "content": str(msg.content)})

            elif isinstance(msg, ToolMessage):
                content = str(msg.content)
                if len(content) > MAX_TOOL_OUTPUT_SIZE:
                    content = content[:MAX_TOOL_OUTPUT_SIZE] + "... [truncated]"
                formatted.append({"role": "tool", "content": f"[RESULT: {content}]"})

        return formatted

    def _extract_text_content(self, content) -> str:
        """Extract text from potentially multimodal content."""
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, str):
                    text_parts.append(item)
                elif isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            return " ".join(text_parts)

        return str(content)

    def _format_conversation_string(
        self, formatted_messages: List[Dict[str, str]]
    ) -> str:
        """Convert formatted messages to a string for the prompt."""
        lines = []
        for msg in formatted_messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def _parse_response(
        self, response_text: str, agent_id: str, session_id: Optional[str]
    ) -> List[Skill]:
        """Parse the LLM response into Skill objects."""
        try:
            # Try to extract JSON from the response
            text = response_text.strip()

            # Handle markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = json.loads(text)

            skills = []
            for skill_data in data.get("skills", []):
                # Handle procedure as list or string
                procedure_raw = skill_data.get("procedure", "")
                if isinstance(procedure_raw, list):
                    # Convert list of steps to numbered string
                    procedure = "\n".join(
                        f"{i + 1}. {step}" for i, step in enumerate(procedure_raw)
                    )
                else:
                    procedure = str(procedure_raw)

                # Handle tools_used as string or list
                tools_raw = skill_data.get("tools_used", [])
                if isinstance(tools_raw, str):
                    tools_used = [t.strip() for t in tools_raw.split(",")]
                else:
                    tools_used = tools_raw

                skill = Skill(
                    agent_id=agent_id,
                    skill_type=SkillType.EXTRACTED,
                    trigger=skill_data.get("trigger", ""),
                    procedure=procedure,
                    tools_used=tools_used,
                    success_criteria=skill_data.get("success_criteria"),
                    session_id=session_id,
                )

                # Only include skills with meaningful content
                if skill.trigger and skill.procedure:
                    skills.append(skill)

            return skills

        except json.JSONDecodeError as e:
            logger.warning(f"[{agent_id}] Failed to parse LLM response as JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"[{agent_id}] Error parsing skill extraction response: {e}")
            return []

    async def extract(
        self,
        messages: List[AnyMessage],
        agent_id: str,
        session_id: str | None = None,
    ) -> SkillExtractionResult:
        """Extract skills from a conversation using the LLM.

        Args:
            messages: The conversation messages
            agent_id: The agent that executed the conversation
            session_id: Optional session ID for correlation

        Returns:
            SkillExtractionResult with extracted skills
        """
        start_time = time.time()

        # Check if worth extracting
        should_extract, reason = self.should_extract(messages)
        if not should_extract:
            return SkillExtractionResult(
                skills=[],
                skipped_reason=reason,
                extraction_time_ms=(time.time() - start_time) * 1000,
            )

        try:
            # Format messages
            formatted = self._format_messages(messages)
            conversation_str = self._format_conversation_string(formatted)

            # Build prompt
            prompt = LLM_EXTRACTION_PROMPT.format(conversation=conversation_str)

            # Call LLM
            llm = self._get_llm()
            response = await llm.ainvoke(prompt)

            # Extract response content as string
            response_content = response.content
            if isinstance(response_content, list):
                # Handle list content (e.g., multimodal responses)
                response_text = " ".join(
                    str(item) if isinstance(item, str) else str(item.get("text", ""))
                    for item in response_content
                    if isinstance(item, (str, dict))
                )
            else:
                response_text = str(response_content) if response_content else ""

            # Parse response
            skills = self._parse_response(
                response_text,
                agent_id,
                session_id,
            )

            extraction_time = (time.time() - start_time) * 1000

            if skills:
                logger.info(f"[{agent_id}] Extracted {len(skills)} skills via LLM")

            return SkillExtractionResult(
                skills=skills,
                extraction_time_ms=extraction_time,
            )

        except Exception as e:
            logger.error(f"[{agent_id}] LLM skill extraction failed: {e}")
            return SkillExtractionResult(
                skills=[],
                skipped_reason=f"Extraction error: {str(e)}",
                extraction_time_ms=(time.time() - start_time) * 1000,
            )
