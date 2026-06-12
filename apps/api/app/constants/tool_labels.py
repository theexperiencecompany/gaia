"""Human-friendly display labels for tool-call loading indicators.

The frontend shows a per-tool-call progress label while the executor runs.
Without curation it title-cases the raw Composio slug, producing ugly,
redundant labels like "Googlecalendar Custom Fetch Events" (with the toolkit
also shown separately as the category).

``TOOL_DISPLAY_NAMES`` curates the user-facing tools with action-phrased
labels. Anything not listed falls back to a cleaned slug (toolkit prefix and
``CUSTOM`` noise stripped, then title-cased) — see ``humanize_tool_name``.

When a tool has a curated label, ``format_tool_call_entry`` also drops the
secondary category line (the icon already conveys the integration), so curated
tools render as a single clean line. Grow this map over time.
"""

# Curated, action-phrased labels keyed by raw tool slug (toolkit + function).
TOOL_DISPLAY_NAMES: dict[str, str] = {
    # ── Google Calendar ────────────────────────────────────────────────
    "GOOGLECALENDAR_CUSTOM_FETCH_EVENTS": "Checking your calendar",
    "GOOGLECALENDAR_CUSTOM_GET_DAY_SUMMARY": "Checking your day",
    "GOOGLECALENDAR_CUSTOM_FIND_EVENT": "Finding the event",
    "GOOGLECALENDAR_CUSTOM_GET_EVENT": "Looking up the event",
    "GOOGLECALENDAR_CUSTOM_CREATE_EVENT": "Adding to your calendar",
    "GOOGLECALENDAR_CUSTOM_PATCH_EVENT": "Updating the event",
    "GOOGLECALENDAR_CUSTOM_DELETE_EVENT": "Removing the event",
    "GOOGLECALENDAR_CUSTOM_ADD_RECURRENCE": "Setting up recurrence",
    "GOOGLECALENDAR_CUSTOM_LIST_CALENDARS": "Checking your calendars",
    "GOOGLECALENDAR_CUSTOM_GATHER_CONTEXT": "Checking your schedule",
    "GOOGLECALENDAR_CREATE_EVENT": "Adding to your calendar",
    "GOOGLECALENDAR_LIST_CALENDARS": "Checking your calendars",
    # ── Gmail ──────────────────────────────────────────────────────────
    "GMAIL_FETCH_EMAILS": "Reading your inbox",
    "GMAIL_FETCH_MESSAGE_BY_THREAD_ID": "Opening the thread",
    "GMAIL_SEND_EMAIL": "Sending the email",
    "GMAIL_CREATE_EMAIL_DRAFT": "Drafting the email",
    "GMAIL_GET_CONTACT_LIST": "Looking up contacts",
    "GMAIL_GET_UNREAD_COUNT": "Counting unread email",
    "GMAIL_MARK_AS_READ": "Marking as read",
    "GMAIL_MARK_AS_UNREAD": "Marking as unread",
    "GMAIL_ARCHIVE_EMAIL": "Archiving the email",
    "GMAIL_STAR_EMAIL": "Starring the email",
    "GMAIL_CUSTOM_GATHER_CONTEXT": "Checking your inbox",
    # ── Notion ─────────────────────────────────────────────────────────
    "NOTION_FETCH_DATA": "Searching Notion",
    "NOTION_FETCH_PAGE_AS_MARKDOWN": "Reading the page",
    "NOTION_INSERT_MARKDOWN": "Writing to Notion",
    "NOTION_MOVE_PAGE": "Moving the page",
    "NOTION_CUSTOM_GATHER_CONTEXT": "Checking Notion",
    # ── Linear ─────────────────────────────────────────────────────────
    "LINEAR_CUSTOM_RESOLVE_CONTEXT": "Resolving Linear context",
    "LINEAR_CUSTOM_GET_MY_TASKS": "Checking your Linear tasks",
    "LINEAR_CUSTOM_SEARCH_ISSUES": "Searching Linear",
    "LINEAR_CUSTOM_GET_ISSUE_FULL_CONTEXT": "Reading the issue",
    "LINEAR_CUSTOM_CREATE_ISSUE": "Creating the issue",
    "LINEAR_CUSTOM_CREATE_SUB_ISSUES": "Creating sub-issues",
    "LINEAR_CUSTOM_CREATE_ISSUE_RELATION": "Linking issues",
    "LINEAR_CUSTOM_GET_ISSUE_ACTIVITY": "Checking issue activity",
    "LINEAR_CUSTOM_GET_ACTIVE_SPRINT": "Checking the sprint",
    "LINEAR_CUSTOM_BULK_UPDATE_ISSUES": "Updating issues",
    "LINEAR_CUSTOM_GET_NOTIFICATIONS": "Checking Linear notifications",
    "LINEAR_CUSTOM_GET_WORKSPACE_CONTEXT": "Checking your workspace",
    "LINEAR_CUSTOM_GATHER_CONTEXT": "Checking Linear",
    # ── Twitter / X ────────────────────────────────────────────────────
    "TWITTER_CUSTOM_BATCH_FOLLOW": "Following on Twitter",
    "TWITTER_CUSTOM_BATCH_UNFOLLOW": "Unfollowing on Twitter",
    "TWITTER_CUSTOM_CREATE_THREAD": "Posting a thread",
    "TWITTER_CUSTOM_SEARCH_USERS": "Searching Twitter",
    "TWITTER_CUSTOM_SCHEDULE_TWEET": "Scheduling a tweet",
    "TWITTER_CUSTOM_GATHER_CONTEXT": "Checking Twitter",
    # ── LinkedIn ───────────────────────────────────────────────────────
    "LINKEDIN_CUSTOM_CREATE_POST": "Posting to LinkedIn",
    "LINKEDIN_CUSTOM_ADD_COMMENT": "Commenting on LinkedIn",
    "LINKEDIN_CUSTOM_GET_POST_COMMENTS": "Reading comments",
    "LINKEDIN_CUSTOM_REACT_TO_POST": "Reacting to the post",
    "LINKEDIN_CUSTOM_DELETE_REACTION": "Removing your reaction",
    "LINKEDIN_CUSTOM_GET_POST_REACTIONS": "Checking reactions",
    "LINKEDIN_CUSTOM_GATHER_CONTEXT": "Checking LinkedIn",
    # ── Google Docs ────────────────────────────────────────────────────
    "GOOGLEDOCS_CUSTOM_SHARE_DOC": "Sharing the doc",
    "GOOGLEDOCS_CUSTOM_CREATE_TOC": "Adding a table of contents",
    "GOOGLEDOCS_CUSTOM_DELETE_DOC": "Deleting the doc",
    "GOOGLEDOCS_CUSTOM_GATHER_CONTEXT": "Checking your docs",
    # ── Google Sheets ──────────────────────────────────────────────────
    "GOOGLESHEETS_CUSTOM_SHARE_SPREADSHEET": "Sharing the spreadsheet",
    "GOOGLESHEETS_CUSTOM_CREATE_PIVOT_TABLE": "Creating a pivot table",
    "GOOGLESHEETS_CUSTOM_SET_DATA_VALIDATION": "Adding data validation",
    "GOOGLESHEETS_CUSTOM_ADD_CONDITIONAL_FORMAT": "Formatting the sheet",
    "GOOGLESHEETS_CUSTOM_CREATE_CHART": "Creating a chart",
    "GOOGLESHEETS_CUSTOM_GATHER_CONTEXT": "Checking your spreadsheets",
    # ── Gather-context snapshots (one per integration) ─────────────────
    "SLACK_CUSTOM_GATHER_CONTEXT": "Checking Slack",
    "GITHUB_CUSTOM_GATHER_CONTEXT": "Checking GitHub",
    "ASANA_CUSTOM_GATHER_CONTEXT": "Checking Asana",
    "TRELLO_CUSTOM_GATHER_CONTEXT": "Checking Trello",
    "TODOIST_CUSTOM_GATHER_CONTEXT": "Checking Todoist",
    "GOOGLETASKS_CUSTOM_GATHER_CONTEXT": "Checking your tasks",
    "GOOGLEMEET_CUSTOM_GATHER_CONTEXT": "Checking your meetings",
    "GOOGLE_MAPS_CUSTOM_GATHER_CONTEXT": "Checking Maps",
    "CLICKUP_CUSTOM_GATHER_CONTEXT": "Checking ClickUp",
    "HUBSPOT_CUSTOM_GATHER_CONTEXT": "Checking HubSpot",
    "AIRTABLE_CUSTOM_GATHER_CONTEXT": "Checking Airtable",
    "REDDIT_CUSTOM_GATHER_CONTEXT": "Checking Reddit",
    "INSTAGRAM_CUSTOM_GATHER_CONTEXT": "Checking Instagram",
    "MICROSOFT_TEAMS_CUSTOM_GATHER_CONTEXT": "Checking Teams",
    # ── GAIA internal ──────────────────────────────────────────────────
    "GAIA_CUSTOM_URGENCY_AGGREGATOR": "Checking what needs attention",
    # ── Native: research & web ─────────────────────────────────────────
    "web_search_tool": "Searching the web",
    "deep_research": "Doing deep research",
    "fetch_webpages": "Reading the page",
    "query_file": "Searching your files",
    # ── Native: daily context ──────────────────────────────────────────
    "gather_context": "Catching up on your day",
    "get_weather": "Checking the weather",
    "generate_image": "Generating an image",
    "create_flowchart": "Creating a flowchart",
    # ── Native: reminders ──────────────────────────────────────────────
    "create_reminder_tool": "Setting a reminder",
    "list_user_reminders_tool": "Checking your reminders",
    "get_reminder_tool": "Looking up the reminder",
    "update_reminder_tool": "Updating the reminder",
    "delete_reminder_tool": "Removing the reminder",
    "search_reminders_tool": "Searching reminders",
    # ── Native: notifications ──────────────────────────────────────────
    "get_notifications": "Checking notifications",
    "search_notifications": "Searching notifications",
    "get_notification_count": "Counting notifications",
    "mark_notifications_read": "Marking notifications read",
    # ── Native: workflows ──────────────────────────────────────────────
    "create_workflow": "Building the workflow",
    "execute_workflow": "Running the workflow",
    "get_workflow": "Opening the workflow",
    "list_workflows": "Checking your workflows",
    "search_triggers": "Finding triggers",
    # ── Native: integrations ───────────────────────────────────────────
    "list_integrations": "Checking your integrations",
    "suggest_integrations": "Finding integrations",
    "connect_integration": "Connecting the integration",
    "check_integrations_status": "Checking integration status",
    "get_integration_instructions": "Reading integration settings",
    "update_integration_instructions": "Saving integration settings",
    # ── Native: memory ─────────────────────────────────────────────────
    "add_memory": "Remembering that",
    "search_memory": "Searching memory",
    # ── Native: tracked todos (GAIA working memory) ────────────────────
    "create_tracked_todo": "Tracking this",
    "update_tracked_todo": "Updating what I'm tracking",
    "update_tracked_todo_canvas": "Updating my notes",
    "search_todo_context": "Checking what I'm tracking",
    "list_tracked_todos": "Reviewing tracked work",
    "complete_tracked_todo": "Wrapping that up",
    # ── Native: support, manual, skills, roadmaps ──────────────────────
    "create_support_ticket": "Creating a support ticket",
    "read_manual": "Reading the manual",
    "install_skill_from_github": "Installing the skill",
    "generate_roadmap": "Building the roadmap",
    # ── Native: coding workspace ───────────────────────────────────────
    "bash": "Running a command",
    "read": "Reading a file",
    "write": "Writing a file",
    "edit": "Editing a file",
    "cancel_executor": "Cancelling the task",
}

# Tokens that carry no meaning in a user-facing label. "TOOL"/"TOOLS" are the
# internal naming suffix (e.g. web_search_tool, create_reminder_tool) and read
# awkwardly when title-cased ("Web Search Tool").
_NOISE_TOKENS = frozenset({"CUSTOM", "TOOL", "TOOLS"})


def humanize_tool_name(raw: str, category: str | None = None) -> str:
    """Return a clean display label for a raw tool slug.

    Curated names win. Otherwise strip a leading toolkit token (when it matches
    ``category``) and ``CUSTOM`` noise, then title-case — so
    ``GOOGLECALENDAR_CUSTOM_FETCH_EVENTS`` becomes ``"Fetch Events"`` rather than
    ``"Googlecalendar Custom Fetch Events"`` (the toolkit is already shown as the
    category, so repeating it is the redundancy we're removing).
    """
    if raw in TOOL_DISPLAY_NAMES:
        return TOOL_DISPLAY_NAMES[raw]

    tokens = raw.split("_")
    normalized_category = (category or "").replace("_", "").lower()

    # Drop a leading toolkit token that duplicates the category.
    if tokens and normalized_category and tokens[0].lower() == normalized_category:
        tokens = tokens[1:]

    tokens = [t for t in tokens if t.upper() not in _NOISE_TOKENS]
    cleaned = " ".join(tokens) if tokens else raw
    return cleaned.replace("-", " ").title()
