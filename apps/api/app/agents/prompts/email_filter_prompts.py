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
