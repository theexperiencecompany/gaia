"""Docstrings for context gathering tools."""

GATHER_CONTEXT_DOC = """
Gather and summarize context from multiple connected providers for a specific date.

This tool aggregates relevant information from the user's connected integrations
and uses AI to produce a concise, actionable summary. Supports past dates for
historical context and future dates for planning.

**Use this when you need:**
- A quick overview of the user's day/context
- The user's schedule, tasks, and commitments
- Pending communications and work items
- Historical context about what happened on a specific day
- Planning context for upcoming dates

**Available providers (12 total):**

| Category | Providers |
|----------|-----------|
| Calendar | calendar (Google Calendar) |
| Email | gmail (with threads) |
| Project Management | linear, asana, trello, clickup |
| Task Management | google_tasks, todoist |
| Code | github (issues, PRs, notifications) |
| Communication | slack (messages, mentions) |
| Documents | notion (pages), google_drive (recent files) |

**What it returns:**
1. **Raw context**: Detailed data from each provider
2. **AI Summary**: Processed, actionable summary including:
   - Overview: Brief 1-2 sentence context
   - Calendar highlights: Key meetings
   - Tasks summary: Important items from all task managers
   - Communications: Key messages/emails
   - Documents: Recent document activity
   - Key items: Top 3-5 items requiring attention

**Args:**
- providers: Optional list of providers to query. If None, queries all available.
- date: Target date (YYYY-MM-DD). Defaults to today. Supports past and future.
- query: Optional focus query (e.g., "project X", "urgent items")
- limit_per_provider: Max items per provider (default: 5, max: 50)

**Context Engineering:**
Only relevant, processed fields are sent to the summarization LLM:
- Calendar: Time + event title only
- Gmail: Sender + subject + unread status
- Linear/Asana/Todoist: Title + priority + state
- GitHub: Repo + title + labels + PR status
- Slack: Channel + user + message preview
- Drive: Filename + type

**Example queries:**
- "What's on my plate today?" -> Full context + summary
- "What happened yesterday?" -> date: yesterday's date
- "What do I have next Monday?" -> date: next Monday's date
- "Context for project Alpha" -> query: "project Alpha"
"""
