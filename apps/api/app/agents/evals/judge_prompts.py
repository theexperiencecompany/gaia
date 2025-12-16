"""
LLM-as-Judge Evaluation Prompts

Prompts used by LLM to evaluate subagent execution trajectory.
These assess tool usage, failure recovery, search behavior, and task completion.

NOTE: Uses Mustache syntax {{variable}} for Opik compatibility.
"""

SUBAGENT_EVALUATION_PROMPT = """You are an expert evaluator assessing an AI subagent's performance on a task.

## Task Context
**User Query:** {{input}}
**Expected Behavior:** {{expected_output}}
**Task Context:** {{context}}

## Agent Execution
**System Prompt Given:**
{{system_prompt}}

**Agent's Final Response:**
{{output}}

**Execution Trajectory:**
{{trajectory}}

**Tool Calls Made:** {{tool_calls}}
**Errors Encountered:** {{errors}}

## Evaluation Criteria

You must evaluate the agent on these 4 dimensions (each 0.0 to 1.0):

### 1. Tool Calling Quality (weight: 0.30)
- Did the agent select appropriate tools for the task?
- Were tool parameters correctly specified?
- Was tool chaining efficient (avoiding redundant calls)?
- Did the agent use available tools effectively?

### 2. Tool Search & Discovery (weight: 0.25)
- Did the agent search for tools when needed?
- Were search queries relevant and well-formed?
- Did the agent persist in finding the right tools?
- Did the agent avoid excessive or repetitive searches?

### 3. Failure Recovery (weight: 0.25)
- How did the agent handle errors or unexpected results?
- Did it try alternative approaches when initial attempts failed?
- Were error messages informative to the user?
- Did the agent degrade gracefully when tasks couldn't be completed?

### 4. Task Completion (weight: 0.20)
- Was the user's request fulfilled?
- Is the final response helpful and accurate?
- Did the agent only decline after exhausting options?
- Was the output appropriately formatted and complete?

## Important Notes
- All tasks given to this agent ARE achievable with available tools
- The agent should NOT refuse tasks prematurely
- The agent should verify assumptions before acting (search before create, list before modify)
- Errors should trigger recovery attempts, not immediate failure

## Response Format
Return ONLY a valid JSON object with this exact structure:
{
    "tool_calling_quality": {
        "score": 0.85,
        "reason": "Brief explanation of tool usage quality"
    },
    "tool_search_discovery": {
        "score": 0.80,
        "reason": "Brief explanation of search behavior"
    },
    "failure_recovery": {
        "score": 0.75,
        "reason": "Brief explanation of error handling"
    },
    "task_completion": {
        "score": 0.90,
        "reason": "Brief explanation of task fulfillment"
    },
    "overall_score": 0.83,
    "summary": "One sentence overall assessment"
}

Evaluate now:"""


TRAJECTORY_SUMMARY_PROMPT = """Summarize this agent execution trajectory concisely:

Trajectory:
{{trajectory}}

Provide a brief summary of:
1. What tools were called and in what order
2. Any errors encountered
3. The final outcome

Keep it under 200 words."""
