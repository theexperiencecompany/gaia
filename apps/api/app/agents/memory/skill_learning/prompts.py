"""
Prompts for skill extraction and self-reflection.

Two approaches are supported:
1. LLM_EXTRACTION_PROMPT - For cheap LLM to extract skills from conversations
2. SELF_REFLECTION_PROMPT - For the executing LLM to document its own experience
"""

# Prompt for cheap LLM to extract procedural skills
LLM_EXTRACTION_PROMPT = """Analyze this agent conversation and extract reusable procedural skills.

A skill is a learned procedure for accomplishing a task type. Only extract skills when:
1. The task was completed successfully (no errors, user got what they wanted)
2. It required 2+ tool calls (not trivial single-step actions)
3. The procedure could help with similar future tasks

For each skill found, output valid JSON with this structure:
{{
    "skills": [
        {{
            "trigger": "Brief description of what request triggers this (e.g., 'send DM on Twitter')",
            "procedure": "1. First step\\n2. Second step\\n3. Third step (as a single string with numbered steps)",
            "tools_used": ["tool1", "tool2"],
            "success_criteria": "How to verify the task completed successfully"
        }}
    ]
}}

IMPORTANT RULES:
- procedure MUST be a single string with numbered steps, NOT a JSON array
- DO NOT include any PII (names, emails, phone numbers, usernames, specific content, URLs, IDs)
- DO NOT extract failed attempts or error recovery (unless recovery was successful)
- DO NOT extract one-off tasks with no reusable pattern
- Keep procedures generic and reusable for similar future requests
- If no skills worth extracting, return: {{"skills": []}}

CONVERSATION:
{conversation}

Extract skills as JSON:"""


# Prompt for the LLM to reflect on its own execution (verbose version)
SELF_REFLECTION_PROMPT = """You just completed a task. Take a moment to reflect and document what you learned.

PURPOSE: This reflection will be stored and retrieved when you (or another instance) encounter similar tasks in the future. Your goal is to make future work EASIER and MORE EFFICIENT by documenting:
- The optimal approach so you don't have to figure it out again
- Pitfalls to avoid so you don't repeat mistakes
- Key insights that aren't obvious from the task description

Think of this as writing notes to your future self who will face the same type of request.

Review the tool calls above carefully and analyze:
1. What was the user trying to accomplish? (generic pattern, not specific details)
2. What approach did you take step-by-step?
3. What worked well and why? What made this approach effective?
4. What did you try that was unnecessary or could be skipped next time?
5. What's the OPTIMAL path if you had to do this again from scratch?
6. Any surprises, edge cases, or gotchas that weren't obvious upfront?

ONLY create a reflection if:
- The task was completed SUCCESSFULLY (user got what they wanted)
- It involved meaningful work (2+ tool calls)
- The approach could help with similar future tasks

DO NOT create a reflection if:
- The task failed or had unrecoverable errors
- It was trivial (single tool call)
- Too specific to be reusable

Output as JSON:
{{
    "trigger": "Generic type of request this handles - how would a user phrase this? (no PII)",
    "procedure": "1. Step one\\n2. Step two\\n3. Step three (the OPTIMAL approach, not what you actually did if that was suboptimal)",
    "tools_used": ["only the essential tools needed for the optimal path"],
    "unnecessary_tools": ["tools you called but weren't actually needed - helps future you skip these"],
    "what_worked": "What approach worked well and WHY. Be specific - this helps future you understand the reasoning.",
    "what_didnt_work": "Failed attempts, dead ends, or unnecessary steps. Future you will thank you for this.",
    "gotchas": "Non-obvious things to watch out for. Edge cases, prerequisites, or things that surprised you.",
    "optimal_approach": "If starting fresh on this type of task, here's the most efficient approach...",
    "success_criteria": "How to verify the task completed successfully"
}}

STRICT RULES:
- procedure MUST be a single string with numbered steps, NOT a JSON array
- NO PII: No names, emails, usernames, user IDs, URLs, or specific content
- Focus on REUSABLE patterns - what applies to ALL similar requests, not just this one
- Be VERBOSE in what_worked, what_didnt_work, and gotchas - these are the most valuable for learning
- Write as if explaining to a colleague who will do this task tomorrow
- If task failed or not worth documenting: {{"skip": true, "reason": "explanation"}}

Your detailed reflection:"""


def format_conversation_for_extraction(messages: list) -> str:
    """Format messages into a string for the extraction prompt."""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        lines.append(f"{role.upper()}: {content}")
    return "\n".join(lines)
