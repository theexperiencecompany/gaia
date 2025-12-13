"""Prompts for email processing and memory extraction."""

# Prompt for extracting memories from user emails
EMAIL_MEMORY_EXTRACTION_PROMPT = """Extract memories ABOUT THE USER from emails they received.

WHAT TO EXTRACT:
- Identity: Name, email, usernames, role, title
- Work: Job, company, projects, skills, industry
- Services: Apps/tools they use, accounts they have, subscriptions
- Interests: Hobbies, topics they follow, communities, newsletters
- Location: City, timezone, work setup (remote/hybrid)
- Relationships: Colleagues, collaborators, frequent contacts
- Preferences: Communication style, tool choices, work style
- Goals: What they're building, learning, or working toward

ONLY STORE IF:
- It's ABOUT THE USER (not about senders or general topics)
- Persistent/stable information (not one-off events)
- Actionable for an AI assistant
- Pattern-based behaviors

DON'T STORE:
- Marketing/promotional content
- Info about other people (unless their relationship to user)
- Trivial details or spam
- Sensitive data (passwords, financial info)
- Generic content that doesn't reveal anything about the user

FORMAT: Present tense, factual statements starting with "User"
Example: "User works as Software Engineer at Acme Corp", "User's email is john@example.com"
"""

EMAIL_WORKFLOW_FILTER_PROMPT = """You are an intelligent email filter. Decide whether this incoming email should trigger the specified workflow.

**Email Details:**
- From: {email_sender}
- Subject: {email_subject}
- Content Preview: {email_preview}

**Workflow to Consider:**
- Title: {workflow_title}
- Description: {workflow_description}
- Purpose: This workflow will execute {workflow_steps_count} automated steps

**Workflow Steps:**
{workflow_steps}

**Decision Criteria:**
- Is this email relevant to the workflow's purpose and steps?
- Would executing these specific workflow steps make sense for this email?
- Is this a legitimate email that warrants automation (not spam/promotional)?
- Does the email content align with what the workflow steps are designed to handle?
- Do the workflow steps provide value for this specific email content?

**Important Guidelines:**
- Only return true if you're confident this email should trigger the workflow
- Consider the ACTUAL STEPS the workflow will execute, not just the title/description
- Consider false positives costly (unnecessary workflow execution)
- Consider false negatives acceptable (user can manually trigger if needed)
- Promotional emails, spam, automated notifications usually should NOT trigger workflows
- Personal emails, actionable requests, important communications usually SHOULD trigger workflows

**Response Format:**
Respond with a JSON object containing:
- should_process: boolean (true/false)
- reasoning: string (brief explanation)
- confidence: number between 0.0 and 1.0

Example: {{"should_process": true, "reasoning": "Email contains actionable request that aligns with workflow steps for email processing and response generation", "confidence": 0.85}}

Make your decision and provide clear reasoning."""
