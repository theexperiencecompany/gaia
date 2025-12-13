SUGGEST_FOLLOW_UP_ACTIONS = """
Based on the conversation, suggest 2-4 highly relevant follow-up actions the user might want to do next. If no genuinely useful actions exist, return an empty array.

CORE PRINCIPLE:
Quality over quantity - only suggest truly useful actions. Better to show nothing than irrelevant suggestions.

ACTION REQUIREMENTS:
- Concise, actionable commands (under 30 characters)
- Should INITIATE processes, not request user input
- When clicked, action text becomes the user's next message

GOOD ACTION TYPES:
- Process starters: "Create reminder", "Set timer", "Write email"
- Data requests: "Show weather", "Get directions"
- Content generation: "Create list", "Draft response"
- Task continuation: "Add another", "Try different style"

DECISION FRAMEWORK:
1. Is the conversation naturally concluded? → Empty array
2. Is the user actively engaged and building toward something? → Suggest actions
3. Is this a simple Q&A that's been answered? → Empty array
4. Would these actions genuinely help the user's next step? → Include them

WHEN TO RETURN EMPTY ARRAY:
- User seems satisfied/done ("Thanks", "Perfect", "Got it")
- Conversation feels complete
- After 3+ consecutive action suggestions
- Simple informational exchange with no clear next steps
- User responses getting shorter (declining engagement)

Ask yourself: "Would I genuinely click these actions if I were the user right now?"

{format_instructions}

Available tools: {tool_names}
Context: {conversation_summary}
"""
