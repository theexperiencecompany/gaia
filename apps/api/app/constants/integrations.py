"""Constants for integration tools."""

# Limits for LLM context to prevent overwhelming responses
MAX_CONNECTED_FOR_LLM = 20
MAX_AVAILABLE_FOR_LLM = 15
MAX_SUGGESTED_FOR_LLM = 10

# Integration connection status values
INTEGRATION_STATUS_CONNECTED = "connected"

# Integration managed_by provider identifiers
MANAGED_BY_MCP = "mcp"
MANAGED_BY_COMPOSIO = "composio"
MANAGED_BY_SELF = "self"

# Known integration IDs
GMAIL_INTEGRATION_ID = "gmail"
GOOGLE_CALENDAR_INTEGRATION_ID = "googlecalendar"

# --- LLM inference (category + marketplace content) -------------------------
# How many tool names to feed the model as context. Category needs less signal
# than content, so it samples fewer.
MAX_TOOLS_FOR_CATEGORY = 10
MAX_TOOLS_FOR_CONTENT = 15

# How many of each content element to request. The frontend needs at least 3
# FAQs for its rich-snippet schema, so never drop FAQ_COUNT below that.
USE_CASES_COUNT = 5
HOW_IT_WORKS_COUNT = 3
FAQ_COUNT = 4

# Fixed set of marketplace categories an integration can be classified into.
INTEGRATION_CATEGORIES = [
    "productivity",  # Notion, Todoist, project management
    "communication",  # Slack, Discord, email
    "developer",  # GitHub, GitLab, CI/CD, databases, infrastructure
    "analytics",  # Data tools, dashboards
    "finance",  # Payments, accounting
    "ai-ml",  # AI services, ML tools, model hosting
    "education",  # Learning platforms, courses, academic tools
    "personal",  # Health, fitness, lifestyle (Strava, etc.)
    "capabilities",  # Agent reasoning & cognitive enhancements only
    "other",  # Fallback
]

CATEGORY_INFERENCE_PROMPT = """
Given the following MCP integration details, classify it into ONE of these categories:
{categories}

Category Guidelines:
- productivity: Task management, notes, project planning, document collaboration
- communication: Messaging, email, team chat, video conferencing
- developer: Code hosting, CI/CD, infrastructure, databases, API tools, deployment platforms
- analytics: Data analysis, dashboards, business intelligence, metrics
- finance: Payments, invoicing, accounting, transactions
- ai-ml: AI model APIs, ML platforms, model hosting services
- education: Learning platforms, academic research, courses, educational content
- personal: Health, fitness, lifestyle, personal tracking
- capabilities: Agent capabilities - reasoning enhancements (thinking frameworks, problem-solving methods), web interaction tools (web search, URL fetching, browser automation), and other fundamental agent abilities. NOT for business services, infrastructure platforms, or domain-specific external APIs.
- other: Anything that doesn't clearly fit the above

Integration Name: {name}
Description: {description}
Available Tools: {tools}
Server URL Domain: {domain}

Respond with ONLY the category name, nothing else.
"""

CONTENT_INFERENCE_PROMPT = """
You are writing marketplace copy for GAIA, a proactive personal AI assistant. \
GAIA connects to third-party tools via MCP and exposes every action as a \
plain-English command — the user tells GAIA what they want and GAIA does it, \
including proactively in the background.

Write rich detail-page content for the following integration.

Integration Name: {name}
Category: {category}
Description: {description}
Available Tools: {tools}
Server URL Domain: {domain}

Voice and quality bar:
- Concrete and specific to THIS integration and its actual tools — never generic
  filler that would fit any product.
- Benefit-led, in GAIA's voice ("GAIA does X for you"), plain-English examples.
- No marketing fluff, no emojis, no first person, no trailing punctuation noise.

Respond with ONLY a JSON object in exactly this shape:
{{
  "use_cases": [{use_cases_count} short strings, each a distinct capability],
  "how_it_works": [{how_it_works_count} objects {{"title": short, "body": 1-2 sentences}} \
covering connect -> instruct in plain English -> GAIA automates it],
  "faqs": [{faq_count} objects {{"question": natural user question, "answer": 1-3 sentences}}]
}}
"""
