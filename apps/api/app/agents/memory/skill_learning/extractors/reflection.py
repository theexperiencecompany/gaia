"""
Self-Reflection Extractor - Has the executing LLM document its own experience.

This approach:
1. After task completion, asks the LLM to reflect on what it did
2. The LLM documents its approach, what worked, and what could be improved
3. This creates higher-quality, more contextual skill documentation

Note: This is designed to be called with the SAME LLM that executed the task,
so it has full context of what happened. This is different from LLMExtractor
which uses a cheap model to analyze the conversation externally.
"""

import json
import time
from typing import List, Optional

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.agents.memory.skill_learning.extractors.base import BaseSkillExtractor
from app.agents.memory.skill_learning.models import (
    Skill,
    SkillExtractionResult,
    SkillType,
)
from app.agents.memory.skill_learning.prompts import SELF_REFLECTION_PROMPT
from app.config.loggers import llm_logger as logger


class ReflectionExtractor(BaseSkillExtractor):
    """Has the executing LLM document its own experience.

    Unlike LLMExtractor which uses a cheap model to analyze conversations,
    this approach asks the original LLM to reflect on its own execution.
    This produces higher-quality documentation since the LLM has full
    context of what it was trying to accomplish.

    Usage:
        This should be called at the end of a successful task execution,
        using the same LLM instance that performed the task.
    """

    def __init__(self, llm: Optional[ChatOpenAI] = None):
        """Initialize the reflection extractor.

        Args:
            llm: The LLM to use for reflection. If None, will create one.
                 Ideally, pass the same LLM that executed the task.
        """
        self._llm = llm

    def set_llm(self, llm: ChatOpenAI) -> None:
        """Set the LLM to use for reflection.

        Call this with the LLM that executed the task for best results.
        """
        self._llm = llm

    def _get_llm(self) -> ChatOpenAI:
        """Get the LLM instance, creating a default if needed."""
        if self._llm is None:
            from app.constants.llm import DEFAULT_OPENAI_MODEL_NAME

            self._llm = ChatOpenAI(
                model=DEFAULT_OPENAI_MODEL_NAME,
                temperature=0.3,  # Slightly creative for reflections
            )
        return self._llm

    def _build_reflection_context(self, messages: List[AnyMessage]) -> str:
        """Build a detailed summary of the conversation for reflection.

        Includes:
        - User request
        - ALL tool calls in order (not deduped) with inputs and outputs
        - Final AI response
        """
        summary_parts = []

        # Extract user request (first HumanMessage)
        for msg in messages:
            if isinstance(msg, HumanMessage):
                content = (
                    msg.content if isinstance(msg.content, str) else str(msg.content)
                )
                summary_parts.append(f"USER REQUEST: {content[:300]}")
                break

        # Build a map of tool_call_id -> ToolMessage content
        tool_results: dict[str, str] = {}
        for msg in messages:
            if isinstance(msg, ToolMessage):
                tool_results[msg.tool_call_id] = str(msg.content)

        # Extract ALL tool calls in order with inputs and outputs
        tool_calls_section = []
        tool_call_idx = 0

        for msg in messages:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for call in msg.tool_calls:
                    tool_call_idx += 1
                    tool_name = call["name"]
                    tool_args = call.get("args", {})

                    # Format args (truncate large values to 100 chars each)
                    args_str = self._format_tool_args(tool_args)

                    # Get corresponding result (truncate to 150 chars)
                    call_id: str = str(call.get("id") or "")
                    result: str = tool_results.get(call_id, "")
                    result_truncated = (
                        result[:150] + "..." if len(result) > 150 else result
                    )

                    tool_calls_section.append(
                        f"{tool_call_idx}. {tool_name}({args_str})\n"
                        f"   → {result_truncated}"
                    )

        if tool_calls_section:
            summary_parts.append(
                "TOOL CALLS (in order):\n" + "\n".join(tool_calls_section)
            )

        # Get final AI response
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                content = str(msg.content)[:300]
                summary_parts.append(f"FINAL RESPONSE: {content}")
                break

        return "\n\n".join(summary_parts)

    def _format_tool_args(self, args: dict) -> str:
        """Format tool arguments, truncating large values."""
        if not args:
            return ""

        formatted_parts = []
        for key, value in args.items():
            value_str = str(value)
            if len(value_str) > 100:
                value_str = value_str[:100] + "..."
            # Escape quotes in value
            value_str = value_str.replace('"', '\\"')
            formatted_parts.append(f'{key}="{value_str}"')

        return ", ".join(formatted_parts)

    def _parse_reflection(
        self, response_text: str, agent_id: str, session_id: Optional[str]
    ) -> Optional[Skill]:
        """Parse the reflection response into a Skill object."""
        try:
            text = response_text.strip()

            # Handle markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = json.loads(text)

            # Check if LLM decided to skip
            if data.get("skip"):
                logger.debug(
                    f"[{agent_id}] LLM skipped reflection: {data.get('reason', 'unknown')}"
                )
                return None

            # Handle procedure as list or string
            procedure_raw = data.get("procedure", "")
            if isinstance(procedure_raw, list):
                # Convert list of steps to numbered string
                procedure = "\n".join(
                    f"{i + 1}. {step}" for i, step in enumerate(procedure_raw)
                )
            else:
                procedure = str(procedure_raw)

            # Handle tools_used as string or list
            tools_raw = data.get("tools_used", [])
            if isinstance(tools_raw, str):
                tools_used = [t.strip() for t in tools_raw.split(",")]
            else:
                tools_used = tools_raw

            # Handle unnecessary_tools as string or list
            unnecessary_raw = data.get("unnecessary_tools", [])
            if isinstance(unnecessary_raw, str):
                unnecessary_tools = [t.strip() for t in unnecessary_raw.split(",")]
            else:
                unnecessary_tools = unnecessary_raw if unnecessary_raw else []

            skill = Skill(
                agent_id=agent_id,
                skill_type=SkillType.REFLECTION,
                trigger=data.get("trigger", ""),
                procedure=procedure,
                tools_used=tools_used,
                success_criteria=data.get("success_criteria"),
                improvements=data.get("improvements"),
                unnecessary_tools=unnecessary_tools,
                optimal_approach=data.get("optimal_approach"),
                what_worked=data.get("what_worked"),
                what_didnt_work=data.get("what_didnt_work"),
                gotchas=data.get("gotchas"),
                session_id=session_id,
            )

            # Only return if we have meaningful content
            if skill.trigger and skill.procedure:
                return skill

            return None

        except json.JSONDecodeError as e:
            logger.warning(f"[{agent_id}] Failed to parse reflection as JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"[{agent_id}] Error parsing reflection: {e}")
            return None

    async def extract(
        self,
        messages: List[AnyMessage],
        agent_id: str,
        session_id: str | None = None,
    ) -> SkillExtractionResult:
        """Generate a self-reflection about the task execution.

        Args:
            messages: The conversation messages
            agent_id: The agent that executed the conversation
            session_id: Optional session ID for correlation

        Returns:
            SkillExtractionResult with the reflection skill (or empty)
        """
        start_time = time.time()

        # Check if worth reflecting on
        should_extract, reason = self.should_extract(messages)
        if not should_extract:
            return SkillExtractionResult(
                skills=[],
                skipped_reason=reason,
                extraction_time_ms=(time.time() - start_time) * 1000,
            )

        try:
            # Build context for reflection
            context = self._build_reflection_context(messages)

            # Build the reflection prompt with context
            full_prompt = f"""TASK SUMMARY:
{context}

---

{SELF_REFLECTION_PROMPT}"""

            # Get reflection from LLM
            llm = self._get_llm()
            response = await llm.ainvoke(full_prompt)

            # Extract response content as string
            response_content = response.content
            if isinstance(response_content, list):
                # Handle list content (e.g., multimodal responses)
                response_text: str = " ".join(
                    str(item) if isinstance(item, str) else str(item.get("text", ""))
                    for item in response_content
                    if isinstance(item, (str, dict))
                )
            else:
                response_text = str(response_content) if response_content else ""

            # Parse the reflection
            skill = self._parse_reflection(
                response_text,
                agent_id,
                session_id,
            )

            extraction_time = (time.time() - start_time) * 1000

            if skill:
                logger.info(f"[{agent_id}] Generated self-reflection skill")
                return SkillExtractionResult(
                    skills=[skill],
                    extraction_time_ms=extraction_time,
                )

            return SkillExtractionResult(
                skills=[],
                skipped_reason="No meaningful reflection generated",
                extraction_time_ms=extraction_time,
            )

        except Exception as e:
            logger.error(f"[{agent_id}] Self-reflection failed: {e}")
            return SkillExtractionResult(
                skills=[],
                skipped_reason=f"Reflection error: {str(e)}",
                extraction_time_ms=(time.time() - start_time) * 1000,
            )
