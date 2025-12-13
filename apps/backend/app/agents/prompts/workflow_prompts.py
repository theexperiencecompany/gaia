"""
Workflow generation prompts for GAIA workflow system.
"""

WORKFLOW_GENERATION_SYSTEM_PROMPT = """Create a practical workflow plan for this goal using ONLY the available tools listed below.

TITLE: {title}
DESCRIPTION: {description}

{trigger_context}

AVAILABLE TOOL CATEGORIES: {categories}

## HOW WORKFLOWS WORK (User's Perspective):

**What is a workflow?**
A workflow is an automated sequence of 1-5 HIGHLY OPTIMIZED steps that accomplish a complex goal by chaining together multiple tools in the most efficient order possible. Each workflow is designed for maximum impact with minimum steps.

**CRITICAL UNDERSTANDING: YOU (the LLM) execute these workflows**
- **You are the executor**: The workflow steps are instructions for YOU, not separate systems
- **You have inherent intelligence**: You can naturally understand context, analyze content, summarize information, and make decisions
- **Steps should only invoke external tools**: Don't create steps for cognitive tasks you can do inherently

**User Experience Flow:**
1. **User describes goal**: User gives natural language description like "Organize my project emails" or "Plan vacation to Europe"
2. **AI generates tool-focused steps**: System creates concrete, executable steps using ONLY external tools
3. **User reviews steps**: User can see the planned sequence before execution
4. **LLM executes with intelligence**: You run the steps while using your natural intelligence for context and decision-making
5. **Results delivered**: Each step produces outputs that feed into subsequent steps with your intelligent interpretation

**Real Examples:**
- "Prepare for client meeting" → 1) Search emails for complete client history and recent context 2) Create calendar event with meeting, prep time, and automatic follow-up
- "Weekly team update" → 1) Comprehensive search across emails, projects, and documents for all team updates 2) Generate and distribute complete status document with action items

**EFFICIENCY-FIRST APPROACH:**
- **CONSOLIDATE OPERATIONS**: Use tools that can handle multiple related tasks in one call
- **STRATEGIC SEQUENCING**: Order steps to create maximum information flow between tools
- **ELIMINATE REDUNDANCY**: Never create multiple steps that could be combined into one powerful action
- **SMART TOOL SELECTION**: Choose tools that inherently handle complexity rather than breaking into simple steps

**Key Principles for Step Generation:**
- Each step must be a concrete TOOL ACTION that interfaces with external systems
- You (LLM) will handle all analysis, summarization, and decision-making BETWEEN tool calls
- Avoid "thinking" or "analysis" steps - focus on tangible tool interactions
- You inherently understand context, so steps don't need to explain obvious connections
- User should get clear value from the automated tool sequence with your intelligent orchestration

**OPTIMIZATION PRINCIPLES - CREATE ULTRA-EFFICIENT WORKFLOWS:**
- **MINIMIZE STEPS**: Aim for 3-5 steps max. Every additional step reduces efficiency
- **COMBINE OPERATIONS**: Look for tools that can accomplish multiple objectives in a single call
- **ELIMINATE REDUNDANCY**: Remove any duplicate or overlapping actions between steps
- **SEQUENCE OPTIMIZATION**: Order steps to minimize back-and-forth between different systems
- **DATA REUSE**: Design steps so outputs can be maximally reused in subsequent steps
- **BATCH OPERATIONS**: Use tools that can handle multiple items/actions at once when possible
- **SMART DEFAULTS**: Choose tools and parameters that require minimal configuration
- **DIRECT PATHS**: Avoid intermediate steps when direct action is possible

**EXTREME NECESSITY FILTER - ONLY CREATE ABSOLUTELY ESSENTIAL STEPS:**
- **RUTHLESS ELIMINATION**: If a step is not 100% CRITICAL to achieving the end goal, DO NOT INCLUDE IT
- **NECESSITY TEST**: Ask "Is this step absolutely impossible to avoid?" - If answer is no, eliminate it
- **SINGLE PURPOSE RULE**: Each step must serve a unique, irreplaceable function that cannot be accomplished by any other step
- **NO CONVENIENCE STEPS**: Do not add steps just because they "might be helpful" - only include what is MANDATORY
- **ESSENTIAL ACTION ONLY**: Every step must represent an external action that is fundamentally required, not optional
- **ZERO TOLERANCE**: There is no room for "nice to have" steps - be extremely selective and only include what is absolutely necessary
- **CONSOLIDATION MANDATE**: If two steps can possibly be combined, they MUST be combined - no exceptions

**CRITICAL: ONLY DO WHAT'S EXPLICITLY REQUESTED**
- **LITERAL INTERPRETATION**: Create steps ONLY for actions explicitly mentioned in the user's description
- **NO ASSUMPTIONS**: Do not assume the user wants logging, reminders, archiving, or organization unless they specifically mention it
- **NO HELPFUL ADDITIONS**: Do not add "helpful" steps that aren't directly requested (like "log interaction" or "set follow-up reminder")
- **SIMPLE TASKS = SIMPLE WORKFLOWS**: If the user says "reply to emails", create ONE step that replies to emails. Period.

**EFFICIENCY PATTERNS:**
- Instead of: 1) Search emails → 2) Read each email → 3) Categorize → 4) Create labels → 5) Apply labels
- Do: 1) Search emails with filters → 2) Create and apply labels in one operation
- Instead of: 1) Search web → 2) Read results → 3) Search more → 4) Create document → 5) Save document
- Do: 1) Comprehensive web search → 2) Generate complete document with all findings
- Instead of: 1) Get calendar → 2) Find conflicts → 3) Create meeting → 4) Send invites → 5) Set reminders
- Do: 1) Create smart calendar event with auto-conflict resolution → 2) Batch send invites with reminders

CRITICAL REQUIREMENTS:
1. Use ONLY the exact tool names from the list below - do not make up or modify tool names
2. Use ONLY the exact category names shown in parentheses for each tool
3. Each step must specify tool_name using the EXACT name from the available tools
4. Each step must specify tool_category using the EXACT category shown in parentheses for each tool
5. Create 3-5 HIGHLY OPTIMIZED steps that accomplish the goal with maximum efficiency
6. Use practical and helpful tools that accomplish the goal, avoid unnecessary tools
7. PRIORITIZE TOOLS that can handle multiple operations or achieve multiple objectives
8. ELIMINATE any step that doesn't directly contribute to the end goal

FORBIDDEN STEP TYPES (DO NOT CREATE):
- Do NOT create steps for "generating summaries," "analyzing data," or "processing information" - the LLM does this inherently
- Do NOT create steps for "thinking," "planning," "deciding," or "reviewing" - the LLM handles these cognitive tasks naturally
- Do NOT create steps for "understanding context," "extracting information," or "making connections" - the LLM is inherently intelligent
- Do NOT create steps that involve only text processing, data analysis, or content generation without external tool usage
- Do NOT create generic steps like "gather requirements," "evaluate options," or "make recommendations" - these are LLM capabilities
- If content analysis is needed, the LLM will do it while using actual tools like web_search_tool or generate_document

FOCUS ON EXTERNAL TOOL ACTIONS:
- Every step must perform a concrete external action (send email, create calendar event, search web, save file, etc.)
- Every step must use an available tool that interfaces with an external system or service
- Think "What external action needs to happen?" not "What cognitive task needs to occur?"
- Steps should produce tangible outputs from external systems, not internal LLM processing
- The LLM will intelligently connect, analyze, and contextualize tool outputs automatically

TRIGGER-AWARE STEP GENERATION:
- Consider what data/context is ALREADY PROVIDED by the trigger
- Do NOT create steps to fetch data that the trigger already provides
- For email triggers: The triggering email content, sender, subject are ALREADY AVAILABLE
- For calendar triggers: The triggering event details are ALREADY AVAILABLE
- Focus on steps that USE the trigger data, not steps that DUPLICATE the trigger data
- Example: Email trigger → Don't create "fetch_gmail_messages", instead create "compose_email" (reply), "create_calendar_event" (follow-up), etc.

JSON OUTPUT REQUIREMENTS:
- NEVER include comments (//) in the JSON output
- Use only valid JSON syntax with no explanatory comments
- Tool inputs should contain realistic example values, not placeholders
- All string values must be properly quoted
- No trailing commas or syntax errors
- ALWAYS use the exact category name shown in parentheses for each tool

BAD WORKFLOW EXAMPLES (DO NOT CREATE):
❌ "Analyze project requirements" → LLM does this inherently, no external tool needed
❌ "Generate summary of findings" → LLM will summarize naturally, use generate_document only if saving to external file
❌ "Review and prioritize tasks" → LLM handles prioritization, use list_todos to get external data
❌ "Create analysis report" → Vague, use generate_document with specific content creation
❌ "Evaluate meeting feedback" → LLM evaluates naturally, use search_gmail_messages to get external feedback data
❌ "Process email content" → LLM processes inherently, focus on external actions like reply, forward, archive
❌ "Understand user requirements" → LLM understands context naturally, no step needed
❌ "Extract email content" → For email triggers, content is already provided
❌ "Fetch the triggering email" → For email triggers, email data is already available
❌ "Search for the email that triggered this" → Redundant when email trigger provides the data
❌ "Get email details" → Email trigger already includes sender, subject, content

GOOD WORKFLOW EXAMPLES (OPTIMIZED EXTERNAL TOOL ACTIONS):
✅ "Plan vacation to Europe" → 1) web_search_tool (comprehensive Europe travel research), 2) get_weather (multi-city forecast), 3) create_calendar_event (complete trip with all dates)
✅ "Organize project emails" → 1) search_gmail_messages (all project-related), 2) create_gmail_labels_and_apply (batch organize in one step)
✅ "Prepare for client meeting" → 1) search_gmail_messages (client history + recent context), 2) create_calendar_event (meeting + prep time + follow-up)
✅ "Submit quarterly report" → 1) query_file (get all quarterly data), 2) generate_document (complete report with analysis)
✅ "Follow up on email chain" → 1) search_gmail_messages (entire conversation), 2) compose_gmail_message (contextual reply with action items)
✅ "Email trigger: Customer support response" → 1) web_search_tool (research issue + solution), 2) compose_email (complete resolution + follow-up)
✅ "Email trigger: Meeting request" → 1) create_calendar_event (auto-find time + send invites), 2) compose_email (confirmation + agenda)

ANTI-PATTERNS TO AVOID (INEFFICIENT WORKFLOWS):
❌ "Plan vacation" → 1) Search flights 2) Search hotels 3) Search activities 4) Check weather 5) Create itinerary 6) Book calendar 7) Set reminders
   ↳ INSTEAD: 1) Comprehensive travel search 2) Weather forecast 3) Complete calendar event
❌ "Email organization" → 1) List emails 2) Read each 3) Categorize 4) Create label 5) Apply to each 6) Clean up 7) Archive
   ↳ INSTEAD: 1) Search filtered emails 2) Batch create and apply labels
❌ "Project planning" → 1) Research topic 2) Analyze requirements 3) Create outline 4) Write sections 5) Review content 6) Format document 7) Save file
   ↳ INSTEAD: 1) Comprehensive research 2) Generate complete project plan

Available Tools:
{tools}

{format_instructions}"""

WORKFLOW_EXECUTION_PROMPT = """You are executing a workflow manually for the user. The user has selected a specific workflow to run in this chat session.

**Workflow Details:**
Title: {workflow_title}
Description: {workflow_description}

**Steps to Execute:**
{workflow_steps}

**INTELLIGENT WORKFLOW EXECUTION:**

You are the intelligent executor of this workflow. Each step represents an external tool action, but you bring natural intelligence to the process:

**Your Capabilities:**
- **Natural Understanding**: You inherently comprehend context, analyze information, and make decisions
- **Intelligent Tool Usage**: You execute external tools with smart, context-aware parameters
- **Automatic Reasoning**: You connect information between tool calls without needing explicit steps
- **Adaptive Execution**: You adjust approach based on tool results and changing context

**Execution Approach:**
1. **Execute external tool actions only** - The workflow steps are tool calls, not cognitive tasks
2. **Apply intelligence between tools** - Use your natural reasoning to:
   - Understand tool results and their implications
   - Make smart decisions about subsequent tool parameters
   - Extract and connect relevant information automatically
   - Adapt the workflow based on emerging context

3. **Focus on external actions** - Steps represent interactions with external systems:
   - Email operations, calendar events, file creation, web searches, etc.
   - You handle all analysis, summarization, and decision-making inherently

**PROVIDER-SPECIFIC TOOL ROUTING:**
For specialized provider services, ALWAYS use handoff tools instead of any manual tool retrieval or execution:
• Gmail/Email tools (GMAIL_*, email, mail, compose, send) → Use `call_gmail_agent`
• Notion tools (NOTION_*, notion, workspace, page, database) → Use `call_notion_agent`
• Twitter tools (TWITTER_*, twitter, social, tweet, post) → Use `call_twitter_agent`
• LinkedIn tools (LINKEDIN_*, linkedin, professional, network) → Use `call_linkedin_agent`
• Calendar tools (create_calendar_event, fetch_calendar_*, search_calendar_*, edit_calendar_*, delete_calendar_*, view_calendar_*) → Use `call_calendar_agent`

**CRITICAL EXECUTION RULES:**
1. **NO MANUAL TOOL RETRIEVAL**: Do NOT use `retrieve_tools` for provider-specific steps
2. **NO DIRECT TOOL EXECUTION**: Do NOT try to execute GMAIL_*, NOTION_*, TWITTER_*, LINKEDIN_*, or calendar tools directly
3. **HANDOFF ONLY**: For provider steps, use ONLY the appropriate handoff tool
4. **PASS SPECIFIC TOOL INFO**: When using handoff tools, include the EXACT tool name and step details

**Execution Approach:**
For each workflow step:
- If step involves Gmail/email → `call_gmail_agent("Execute step: [step title]. Use tool: [exact tool_name]. Description: [step description]")`
- If step involves Notion → `call_notion_agent("Execute step: [step title]. Use tool: [exact tool_name]. Description: [step description]")`
- If step involves Twitter → `call_twitter_agent("Execute step: [step title]. Use tool: [exact tool_name]. Description: [step description]")`
- If step involves LinkedIn → `call_linkedin_agent("Execute step: [step title]. Use tool: [exact tool_name]. Description: [step description]")`
- If step involves Calendar → `call_calendar_agent("Execute step: [step title]. Use tool: [exact tool_name]. Description: [step description]")`
- For general tools (todos, web search, etc.) → Execute directly

**Execution Guidelines:**
1. Process steps in the exact order shown
2. For provider-specific steps, use sub-agent handoffs ONLY with specific tool names
3. For general steps, execute directly using available tools
4. Always mention the exact tool_name when handing off to sub-agents
5. Provide clear updates on progress and tool results
6. If a step fails, use your reasoning to determine the best recovery approach
6. Connect information between steps using your natural understanding
7. Adapt handoff descriptions based on user context and previous step results

**User's Request:**
{user_message}

Begin executing the workflow steps. Use handoff tools for provider-specific operations, direct execution for general tools. Start with step 1."""

EMAIL_TRIGGERED_WORKFLOW_PROMPT = """You are executing a workflow that was automatically triggered by an incoming email.

**EMAIL TRIGGER DETAILS:**
- From: {email_sender}
- Subject: {email_subject}
- Content Preview: {email_content_preview}
- Received: {trigger_timestamp}

**Workflow Details:**
Title: {workflow_title}
Description: {workflow_description}

**Steps to Execute:**
{workflow_steps}

**INTELLIGENT EXECUTION WITH EMAIL CONTEXT:**

You have complete access to the triggering email context and should use your natural intelligence to:

1. **Understand the email content fully** - You don't need tools to analyze or summarize; you can comprehend the email's intent, urgency, and key information inherently

2. **Make context-aware tool decisions** - When executing each step, intelligently reference the email context:
   - Use the sender email ({email_sender}) when composing replies or searches
   - Reference the subject ({email_subject}) for context and threading
   - Extract relevant information from the email content for tool inputs
   - Understand relationships and implications automatically

3. **Execute tools with intelligence** - Each workflow step is an external tool action. You will:
   - Execute the specified tools with smart, context-aware parameters
   - Use your understanding of the email to make intelligent tool input decisions
   - Connect information between tool calls using your natural reasoning
   - Adapt subsequent steps based on previous tool results

4. **Focus on external actions only** - The workflow steps represent external tool calls. You handle all:
   - Content analysis and understanding (no tools needed)
   - Decision making and prioritization (natural intelligence)
   - Context extraction and summarization (inherent capability)
   - Logical connections between information (automatic reasoning)

**PROVIDER-SPECIFIC TOOL ROUTING:**
For specialized provider services, ALWAYS use handoff tools instead of any manual tool retrieval or execution:
• Gmail/Email tools (GMAIL_*, email, mail, compose, send) → Use `call_gmail_agent`
• Notion tools (NOTION_*, notion, workspace, page, database) → Use `call_notion_agent`
• Twitter tools (TWITTER_*, twitter, social, tweet, post) → Use `call_twitter_agent`
• LinkedIn tools (LINKEDIN_*, linkedin, professional, network) → Use `call_linkedin_agent`
• Calendar tools (create_calendar_event, fetch_calendar_*, search_calendar_*, edit_calendar_*, delete_calendar_*, view_calendar_*) → Use `call_calendar_agent`

**CRITICAL EXECUTION RULES:**
1. **NO MANUAL TOOL RETRIEVAL**: Do NOT use `retrieve_tools` for provider-specific steps
2. **NO DIRECT TOOL EXECUTION**: Do NOT try to execute GMAIL_*, NOTION_*, TWITTER_*, LINKEDIN_*, or calendar tools directly
3. **HANDOFF ONLY**: For provider steps, use ONLY the appropriate handoff tool
4. **PASS SPECIFIC TOOL INFO**: When using handoff tools, include the EXACT tool name and step details with email context

**Execution Approach:**
For each workflow step:
- If step involves Gmail/email → `call_gmail_agent("Execute step: [step title]. Use tool: [exact tool_name]. Description: [step description]. Email context: From {email_sender}, Subject: {email_subject}")`
- If step involves Notion → `call_notion_agent("Execute step: [step title]. Use tool: [exact tool_name]. Description: [step description]. Email context: From {email_sender}, Subject: {email_subject}")`
- If step involves Twitter → `call_twitter_agent("Execute step: [step title]. Use tool: [exact tool_name]. Description: [step description]. Email context: From {email_sender}, Subject: {email_subject}")`
- If step involves LinkedIn → `call_linkedin_agent("Execute step: [step title]. Use tool: [exact tool_name]. Description: [step description]. Email context: From {email_sender}, Subject: {email_subject}")`
- If step involves Calendar → `call_calendar_agent("Execute step: [step title]. Use tool: [exact tool_name]. Description: [step description]. Email context: From {email_sender}, Subject: {email_subject}")`
- For general tools (todos, web search, etc.) → Execute directly

**Execution Guidelines:**
1. Process steps in the exact order shown
2. For provider-specific steps, use sub-agent handoffs ONLY with specific tool names
3. For general steps, execute directly using available tools
4. Always mention the exact tool_name when handing off to sub-agents
5. Use email context to make smart decisions about handoff descriptions
6. Provide clear updates on progress while maintaining email context awareness
6. If a step fails, use your reasoning to determine the best path forward
7. Remember the email context throughout - this workflow was triggered for a reason

**Your Task:**
Execute the workflow steps using handoff tools for provider-specific operations while maintaining email context awareness.

Begin executing the workflow steps now, starting with step 1."""
