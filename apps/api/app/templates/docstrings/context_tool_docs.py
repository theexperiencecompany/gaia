"""Docstrings for context gathering tools."""

GATHER_CONTEXT_DOC = """
Gather rich, comprehensive context from all the user's connected integrations for a specific date.

This tool queries all connected providers in parallel and fetches detailed structured data
from each — schedule, communications, tasks, and more.

**Use this when the user asks:**
- "What's my day looking like?"
- "What's on my plate / what do I have going on?"
- "Catch me up", "Any updates?"
- "What happened yesterday?" / "What's coming up this week?"
- "What do I need to focus on today?"
- "Any urgent items?"

**Providers (auto-detects which are connected):**

| Category | Providers |
|----------|-----------|
| Calendar | calendar (Google Calendar — events, attendees, video links), google_meet (upcoming Meet calls) |
| Email | gmail (inbox unread, snippets, starred, important) |
| Project Mgmt | linear (issues, priority), asana (tasks), trello (cards), clickup (tasks) |
| Task Mgmt | google_tasks (with due dates), todoist (with priority) |
| Code | github (issues, PRs, review requests, notifications) |
| Communication | slack (messages, @mentions, unread), teams (Microsoft Teams — teams, chats, unread), reddit (subscriptions, unread messages) |
| Social | twitter (profile, recent tweets), instagram (profile, recent media), linkedin (profile, recent posts) |
| Documents | notion (recent pages), google_docs (recent docs), google_sheets (recent spreadsheets) |
| CRM | hubspot (recent contacts and deals) |
| Database | airtable (bases and tables) |
| Maps | google_maps (API connectivity, available services) |

Each provider is self-contained — connected integrations are queried in parallel.

**What it returns:**
Structured data per provider (events, emails, tasks, messages, etc.)

**Smart behavior:**
- Only queries integrations the user has actually connected (skips unconnected ones)
- Fetches @mentions separately in Slack for high-signal items
- Fetches inbox unread in Gmail regardless of date filter for actionable context
- Fetches PR review requests in GitHub (not just assigned items)

**Args:**
- providers: Optional list of specific providers. If None, auto-detects connected.
- date: Target date (YYYY-MM-DD). Defaults to today. Supports past and future.

**Examples:**
- Full day context: GAIA_GATHER_CONTEXT(date="2026-03-01")
- Yesterday: GAIA_GATHER_CONTEXT(date="2026-02-28")
- Just email + calendar: GAIA_GATHER_CONTEXT(providers=["gmail", "calendar"])
"""
