"""
Workflow generation prompts for GAIA workflow system.
"""

# =============================================================================
# WORKFLOW CREATION SUBAGENT TASK TEMPLATES
# =============================================================================

WORKFLOW_CREATION_NEW_TASK_TEMPLATE = """Create a workflow based on this request:

"{workflow_request}"
{hints_section}
Process this request:
1. If the request is clear and unambiguous, finalize immediately
2. If anything is unclear (what it should do, when to run), ask ONE clarifying question
3. For integration triggers, use search_triggers to find appropriate triggers
4. For scheduled triggers, convert natural language to cron expression

Always include a JSON block in your response (either clarifying or finalized type).
"""

WORKFLOW_CREATION_HINTS_TEMPLATE = """
The executor provided these hints (use as suggestions, override based on user input):
{hints}
"""

WORKFLOW_CREATION_FROM_CONVERSATION_TASK_TEMPLATE = """Create a workflow from this conversation context:

Title suggestion: {suggested_title}
Summary: {summary}

Steps identified from conversation:
{steps_text}

Integrations used: {integrations_used}
{user_request_section}
{hints_section}
Process this context:
1. Summarize what was accomplished and confirm saving as workflow
2. Determine trigger type - ask if not obvious from context
3. For integration triggers, use search_triggers
4. For scheduled triggers, convert natural language to cron
5. Once confirmed, output finalized JSON

Always include a JSON block in your response (either clarifying or finalized type).
"""

WORKFLOW_CREATION_USER_REQUEST_TEMPLATE = """
User's additional request: "{workflow_request}"
"""

WORKFLOW_CREATION_RETRY_TEMPLATE = """Your previous response had an invalid JSON output. Error: {error}

Please respond again with a VALID JSON block. Required format:

For clarifying questions:
```json
{{"type": "clarifying", "message": "Your question here"}}
```

For finalized workflow:
```json
{{
    "type": "finalized",
    "title": "Workflow Title",
    "description": "1-2 sentence summary for UI cards",
    "prompt": "Detailed step-by-step instructions. Include numbered steps, specific integrations, data sources, and expected outputs.",
    "trigger_type": "manual|scheduled|integration",
    "cron_expression": "0 9 * * *",
    "trigger_slug": "TRIGGER_SLUG_HERE",
    "direct_create": true
}}
```

Note: cron_expression required for scheduled, trigger_slug required for integration.
Set direct_create: true only for simple, unambiguous workflows.

Original request:
{original_task}
"""


# =============================================================================
# WORKFLOW GENERATION PROMPTS (existing)
# =============================================================================

# Template for generating detailed todo execution prompt
TODO_WORKFLOW_PROMPT_TEMPLATE = """This workflow was automatically generated from a todo item to help the user accomplish their task.

**Purpose:** Break down this todo into actionable automated steps. The user will click "Run Workflow" when they're ready to execute it, and the AI assistant will carry out each step in sequence.

**Important Context:**
- This is a todo-driven workflow - focus on practical steps to complete the user's task
- Each step should use external tools to accomplish concrete actions
- Keep steps minimal and efficient - only include what's necessary to complete the todo
- The user expects this workflow to help them finish their todo item faster

**Todo Task:** {title}
{details_section}

Generate practical, executable steps that will help the user complete: "{title}"
"""

# Short display description for todo workflows
TODO_WORKFLOW_DESCRIPTION_TEMPLATE = "Automated workflow to complete: {title}"

WORKFLOW_GENERATION_SYSTEM_PROMPT = """Create a practical workflow plan for this goal using ONLY the available tools listed below.

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
1. Use ONLY the exact category names from the AVAILABLE TOOL CATEGORIES above
2. Each step must specify 'category' using the EXACT category name (e.g., "gmail", "googlecalendar", "todos", "reminders")
3. Create 3-5 HIGHLY OPTIMIZED steps that accomplish the goal with maximum efficiency
4. The execution agent will use `handoff` to delegate to subagents based on category
5. Categories like gmail, notion, github, slack, googlecalendar route to specialized subagents
6. Categories like todos, reminders, search, development use direct tool execution
7. ELIMINATE any step that doesn't directly contribute to the end goal
8. Use `gaia` category for steps that involve GAIA's own reasoning, writing, analysis, or synthesis with NO external tool call.
   Examples: summarize fetched content, draft a message or brief, classify items, generate an outline, extract key points, write a report section.
   Use `gaia` instead of hallucinating categories like "documents" or "general" for pure-reasoning steps.
   Do NOT use `gaia` if the step calls any external system — use the appropriate integration category instead.

## ABSTRACT STEP DESIGN:
**Steps are GENERIC descriptions, NOT specific tool calls!**

- **You generate WHAT should happen**, the execution LLM will decide HOW
- **Use descriptive titles**: "Search for client context" not "GMAIL_SEARCH_MESSAGES"
- **Focus on intent**: The `category` provides routing, the `description` provides context
- **Let execution decide**: The executing LLM has full context and will choose optimal tools
- **Think high-level**: "Create follow-up reminder" instead of "create_todo with title=..."

**Step Structure:**
- `title`: Human-readable step name (what action to take)
- `category`: Which system/subagent handles this step (gmail, notion, todos, reminders, etc.)
- `description`: Detailed context about what this step should accomplish
- `inputs`: Optional hints/parameters, but the executor makes final decisions

**Example Step:**
```json
{{
  "title": "Send meeting follow-up",
  "category": "gmail",
  "description": "Compose and send a follow-up email summarizing the meeting decisions and assigned action items"
}}
```
NOT:
```json
{{
  "title": "GMAIL_SEND_EMAIL",
  "category": "gmail",
  "description": "Send an email"
}}
```


FORBIDDEN STEP TYPES (DO NOT CREATE):
- Do NOT create steps for "generating summaries," "analyzing data," or "processing information" - the LLM does this inherently
- Do NOT create steps for "thinking," "planning," "deciding," or "reviewing" - the LLM handles these cognitive tasks naturally
- Do NOT create steps for "understanding context," "extracting information," or "making connections" - the LLM is inherently intelligent
- Do NOT create steps that involve only text processing, data analysis, or content generation without external tool usage
- Do NOT create generic steps like "gather requirements," "evaluate options," or "make recommendations" - these are LLM capabilities
- If content analysis is needed, the LLM will do it while using actual tools like web_search_tool
- Do NOT use `category: "notifications"` for any step. GAIA automatically sends the user a notification after every workflow run — you never need to explicitly deliver an alert or push message. If a step needs to prepare a summary or message for the user (e.g. "summarize findings to surface to the user"), use `category: "gaia"` instead.

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

BAD WORKFLOW EXAMPLES (DO NOT CREATE):
❌ "Analyze project requirements" → LLM does this inherently, no external tool needed
❌ "Generate summary of findings" → LLM will summarize naturally; only add a step if it performs a concrete external action
❌ "Review and prioritize tasks" → LLM handles prioritization, use list_todos to get external data
❌ "Create analysis report" → Vague; specify the concrete external action (e.g. compose_gmail_message to send it)
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
✅ "Email quarterly report" → 1) query_file (get all quarterly data), 2) compose_gmail_message (report with analysis)
✅ "Follow up on email chain" → 1) search_gmail_messages (entire conversation), 2) compose_gmail_message (contextual reply with action items)
✅ "Email trigger: Customer support response" → 1) web_search_tool (research issue + solution), 2) compose_email (complete resolution + follow-up)
✅ "Email trigger: Meeting request" → 1) create_calendar_event (auto-find time + send invites), 2) compose_email (confirmation + agenda)

ANTI-PATTERNS TO AVOID (INEFFICIENT WORKFLOWS):
❌ "Plan vacation" → 1) Search flights 2) Search hotels 3) Search activities 4) Check weather 5) Create itinerary 6) Book calendar 7) Set reminders
   ↳ INSTEAD: 1) Comprehensive travel search 2) Weather forecast 3) Complete calendar event
❌ "Email organization" → 1) List emails 2) Read each 3) Categorize 4) Create label 5) Apply to each 6) Clean up 7) Archive
   ↳ INSTEAD: 1) Search filtered emails 2) Batch create and apply labels
   ↳ INSTEAD: 1) Comprehensive research 2) Generate complete project plan

   
TITLE: {title}
DESCRIPTION: {description}

{trigger_context}

AVAILABLE TOOL CATEGORIES: {categories}

Available Tools:
{tools}"""


SIGNAL_MATCHING_INSTRUCTIONS = """TRACKED TODOS (Working Memory)
{tracked_todos_context}

SIGNAL MATCHING (do this BEFORE running the workflow):
Check whether the incoming signal (email, calendar event, slack message, etc.) relates to any
tracked todo listed above. Match by:
- Email address or sender name appearing in a todo's Key Details
- Thread ID, event ID, or issue ID matching a todo's Key Details
- Subject or content that clearly relates to a todo's title or description
- Same person, project, or topic as an active todo

If a match is found, update that todo's canvas with the new signal information using
update_tracked_todo_canvas (mode "append" or "section" — do not read the canvas and rewrite the
whole thing). Be verbose, this is GAIA's working memory: include email addresses, thread IDs,
event IDs, timestamps; quote the key sentences (not whole emails); update Current State; add a
Timeline entry "- {date}: {what happened}".

This matching step only MATCHES and UPDATES existing tracked todos — do not create a new one
just because a signal arrived. (Creating still follows the normal rule during the workflow's
own write actions; a read-only or summary workflow never creates one, since fetching, listing,
or summarizing data is not trackable work.) If nothing matches, just run the workflow.
"""


WORKFLOW_EXECUTION_PROMPT = """You're running the user's saved workflow on their behalf. This is an automated run, so finish it end to end and don't ask the user anything.

**Workflow:** {workflow_title}
**Goal:** {workflow_description}

**Steps the executor should carry out, in order:**
{workflow_steps}
{signal_matching_section}

Hand the whole workflow to the executor as ONE task in a single call_executor call, with the goal and every step included in that one call. Do not make a separate call_executor call per step and do not split the work across turns: one delegation covers the entire workflow, then let the executor's result come back. Don't summarize anything yourself before the executor returns.

If this workflow only fetches, reads, lists, or summarizes data, do NOT create a tracked todo for it — there is nothing to track or follow up on.

{user_message}"""

# =============================================================================
# MAGIC PROMPT GENERATOR — system prompt & user template
# =============================================================================

WORKFLOW_PROMPT_GENERATION_SYSTEM = """You are writing execution instructions for GAIA, an AI workflow agent.

The instructions are read by the agent at execution time. Write directly to it in imperative second-person ("Fetch...", "Search...", "Send..."). Never third-person.

The agent is intelligent — it decides how to call tools, process data, format output, handle retries, and structure results on its own. Your job is to describe the GOAL and the desired OUTCOME, not the mechanics.

NEVER include in instructions:
- Implementation details: "store in JSON", "extract fields", "parse response", "retry once", "log the error"
- Data handling: "for each email extract X, Y, Z", "create an object", "build an array"
- Trigger context: what triggers the workflow, when it fires, what event starts it, "when a new email arrives", "before each meeting", "check calendar for upcoming events" — the trigger system handles this separately and the agent already knows WHY it was invoked
- Scheduling language: cron, times, "every morning", "10 minutes before"
- Retry/error logic: the agent handles failures automatically
- Step-by-step procedures: the system generates steps separately

The user's description is raw input — distill it to intent. Strip away the WHEN (trigger) and focus on the WHAT (action). Examples:
- "10 mins before every meeting check my inbox" → intent is "show me relevant emails for an upcoming meeting", NOT "check calendar then fetch emails"
- "when I get an email, summarize it" → intent is "summarize the incoming email"
- "extract sender, subject, first 200 chars, store as JSON" → intent is "summarize new emails"

Write 80–150 words of plain prose. No bullets, no headers, no code fences. Name the integrations and describe what the user should receive. One sentence for fallback behavior.

Improve mode: sharpen existing instructions — add specificity and edge cases only. Don't restructure.

Trigger suggestion rules (apply in STRICT priority order):
1. INTEGRATION FIRST — scan the available triggers list below. If the user's intent involves a service that has a trigger, YOU MUST use it. This is not optional.
   - "before meeting" / "meeting starts" / "calendar event" → calendar_event_starting_soon
   - "new email" / "check inbox" / "when I get an email" → gmail_new_message
   - "new commit" / "push to repo" → github_commit_event
   - "new message in slack" → slack_new_message
   - "new issue" / "issue created" → github_issue_added or linear_issue_created
   Even if the user also mentions a time interval ("every 10 mins check email"), the integration trigger takes priority.
2. SCHEDULE — only if a cadence is mentioned AND no integration trigger matches the described event.
3. MANUAL — default when nothing implies timing or an event.
- trigger_name MUST be the exact slug from the available triggers list
- Common cron: daily 9 AM = 0 9 * * *, weekdays 8 AM = 0 8 * * 1-5, every Monday = 0 10 * * 1, hourly = 0 * * * *"""

WORKFLOW_PROMPT_GENERATION_TEMPLATE = """{title_section}{description_section}
{trigger_hint}
{integrations_hint}
{available_triggers}
{existing_section}
{mode_instruction}

{format_instructions}"""


EMAIL_TRIGGERED_WORKFLOW_PROMPT = """You're running the user's saved workflow, triggered automatically by an incoming email. This is an automated run, so finish it end to end and don't ask the user anything.

**Triggering email:**
- From: {email_sender}
- Subject: {email_subject}
- Preview: {email_content_preview}
- Received: {trigger_timestamp}

**Workflow:** {workflow_title}
**Goal:** {workflow_description}

**Steps:**
{workflow_steps}
{signal_matching_section}

Use the email above as context for the run, treat the whole workflow as one job, and get it all done in this run. If this workflow only fetches, reads, or summarizes data, do NOT create a tracked todo for it.
"""
