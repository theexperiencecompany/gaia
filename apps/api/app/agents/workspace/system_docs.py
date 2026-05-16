"""Canonical workspace docs (INDEX.md + per-category GUIDE.md).

These are the *harness* the agent reads to understand the FS layout — what
each directory means, what is mutable, where outputs surface in the UI. The
content is written once at session bootstrap into each user's workspace; one
source of truth lives here so we can iterate on the prose without touching
storage code.

Files are not symlinks in v1: the sandbox bind-mount only exposes the user's
own subtree, so the canonical content is materialized into each user's
workspace by `ensure_session_dirs`. A future revision can switch to symlinks
once the sandbox template binds a `_system/` mount alongside the user root.
"""

from __future__ import annotations

INDEX_MD = """# /workspace — your operating environment

This is your persistent root inside the sandbox. Everything you create
here survives across conversations for this user.

## Top-level layout

    sessions/         per-conversation working trees (see sessions/GUIDE.md)
    integrations/     connected integrations: subagents, prompts, skills
                      (present only when the user has connected one)
    skills/           reusable agent skills (when present)
    pinned/           cross-session files the user has pinned for reuse

## How to navigate

Before operating on any directory, read its `GUIDE.md`. It tells you what
that area is for, what is mutable vs read-only, and the action conventions
for that domain. If a directory has no `GUIDE.md`, default to treating its
contents as read-only and ask before modifying.

The conversation you're in right now has its working tree at:

    /workspace/sessions/<your-conversation-id>/

Start there for any task involving files the user attached or outputs you
need to surface back to them.
"""

SESSIONS_GUIDE_MD = """# Sessions — how to work inside the user's conversation tree

Each conversation gets its own working directory at:

    /workspace/sessions/<conv_id>/

This is *your* tree for the current turn. Everything below is reachable via
relative paths (`./user-uploaded/foo.png`, `./scratch/work.py`,
`./artifacts/out.html`) once you `cd` into the session root, which is also
your default working directory for `bash`.

## Layout

    user-uploaded/   files the user attached to this conversation.
                     READ-ONLY. Never mutate in place — copy to scratch/ first.
    scratch/         your private working area. Anything goes — intermediate
                     scripts, downloaded data, half-finished output. Not shown
                     to the user.
    artifacts/       USER-VISIBLE outputs. Any file you write here renders as
                     a card in the chat UI the instant it appears:
                       - HTML, Markdown, images → preview inline
                       - csv/json/code/text     → download card with preview
                       - other binaries         → download card
                     Pick a descriptive filename with a real extension.

## Rules

1. **Uploads are read-only.** If you need to modify an uploaded file, copy
   it to `scratch/` first, then operate on the copy. Writes/edits directly
   into `user-uploaded/` are rejected by the write/edit tools and would
   confuse the user about what they originally sent.
2. **Final outputs go in `artifacts/`.** The user sees them immediately, no
   extra step. Don't tell the user "the file is in scratch/foo" — move or
   copy it to `artifacts/` so they can actually open it.
3. **Use bash.** You have a full Linux shell with python, node, sudo, and
   pip/npm install. Install whatever you need on the fly — it persists for
   the rest of the session.
4. **Don't ask the user where files are.** If they attached something, it's
   already at `./user-uploaded/<name>` — list the directory if you're not
   sure of the exact filename.

## Subagent sessions (per-integration)

When you call a per-integration subagent (e.g. gmail, slack), that subagent
gets its own scratch space at:

    /workspace/sessions/<conv_id>/<integration>-<datetime>/scratch/

The subagent uses it for its own intermediate work. **User-visible output
from a subagent still goes in the parent session's `artifacts/`** — that's
the single place the UI watches.

## Typical recipe — processing an attached file

```bash
ls user-uploaded/                                 # confirm filename
cp user-uploaded/<name> scratch/<name>            # never mutate the original
# write a script in scratch/, run it, produce output in scratch/
mv scratch/<output> artifacts/<output>            # user sees the card
```

That's it. No special tools, no upload pipeline, no follow-up steps — the
moment you write into `artifacts/` the card appears.
"""


INTEGRATIONS_GUIDE_MD = """# Integrations — how connected services live on disk

Each external service the user has connected (gmail, googlecalendar, slack,
…) gets its own subdirectory:

    integrations/
        GUIDE.md           (this file)
        <integration>/
            agent/
                prompt.md           the subagent's persona + behavioral rules
                skills/<slug>/
                    skill.md        a single named capability — when to use
                                    it and how. Read these on demand; the
                                    subagent's runtime context already lists
                                    them by title and path.

## Rules

1. **Everything here is read-only.** These files are materialized by the
   runtime when the user connects an integration. Edits won't persist — and
   wouldn't be honored by the subagent's prompt builder anyway.
2. **Skills are addressable docs, not code.** Each `skill.md` is a
   self-contained recipe. The subagent decides which one applies and `cat`s
   it before acting.
3. **One integration per subagent.** The gmail subagent uses
   `integrations/gmail/agent/`; the googlecalendar subagent uses
   `integrations/googlecalendar/agent/`. They never cross-read.
"""

# DEPRECATED: kept for back-compat with one or two callers that still
# reference the old shape. The real source of truth is now
# ``app.agents.workspace.skill_loader.load_builtin_skills()`` which reads the
# canonical SKILL.md files from disk so the FS layout contains the *complete*
# skill body, not a hand-written stub. New code should use the loader.
_DEPRECATED_INTEGRATION_AGENTS_STUB: dict[str, dict[str, object]] = {
    "googlecalendar": {
        "prompt": """# Google Calendar subagent

You are the Google Calendar specialist subagent. Your job is to read and
modify the user's calendar via the Google Calendar tools, never via a
direct API or another integration. You operate on behalf of the executor;
return concise results when done — the executor will narrate them to the
user.

Defaults: user's primary calendar, the user's timezone, the next 7 days.
Always confirm before deleting events or making cross-account changes.
""",
        "skills": {
            "create-event": (
                "Create a calendar event",
                """# Create a calendar event

Use when the user wants to schedule something new.

Required: title, start datetime, end datetime (or duration).
Optional: attendees, location, description, recurrence rule.

Always:
- Resolve relative times ("tomorrow 3pm") against the user's timezone.
- Default duration to 30 min if the user didn't specify.
- Skip adding attendees you weren't asked to invite — confirm first.
""",
            ),
            "find-free-time": (
                "Find a free time slot",
                """# Find a free time slot

Use when the user asks "when am I free", "find a time for X", or wants to
schedule against attendees' availability.

Inputs: window (start/end), duration, optional attendees, optional working
hours, optional buffer between meetings.

Return the top 3 slots. Prefer slots that respect the user's working hours
and existing focus blocks.
""",
            ),
            "list-events": (
                "List upcoming events",
                """# List upcoming events

Use for "what's on my calendar", "what's next", "today's agenda".

Inputs: window (default: rest of today + tomorrow), calendar id (default:
primary). Return: title, time range, location, attendees (when relevant).
Skip declined events unless the user asked to see them.
""",
            ),
        },
    },
    "gmail": {
        "prompt": """# Gmail subagent

You are the Gmail specialist subagent. Read and send mail via the Gmail
tools, never another email service. Return concise results to the
executor; it narrates them to the user.

Defaults: the user's primary mailbox. Drafts go to Drafts (never send
without confirmation unless the user explicitly said "send"). For
sensitive actions (delete, archive at scale, forward to a new address),
ask before acting.
""",
        "skills": {
            "send-email": (
                "Send or draft an email",
                """# Send or draft an email

Use for "email <person> about X", "reply to <subject>", "draft a note to …".

Default action is **draft** unless the user explicitly said send/just send
it. Subject and body must be concrete — never leave `[your name]`-style
placeholders.

Required: to (email or contact name to resolve), subject, body.
Optional: cc, bcc, attachments, reply_to_thread.
""",
            ),
            "search-inbox": (
                "Search the inbox",
                """# Search the inbox

Use for "find the email from <person>", "did <person> reply", "show me
threads about X".

Inputs: free-text query, optional from/to filters, optional date range.
Return: subject, sender, date, short snippet, message id. Sort by date
desc by default.
""",
            ),
            "summarize-thread": (
                "Summarize an email thread",
                """# Summarize an email thread

Use when the user asks "what did <person> say", "summarize this thread",
or wants to act on a long back-and-forth without reading every message.

Input: thread id (preferred) or a free-text descriptor that uniquely
identifies the thread. Return: 1-3 sentence summary + the open question
or ask, if any.
""",
            ),
        },
    },
    "googlesheets": {
        "prompt": """# Google Sheets subagent

You are the Google Sheets specialist subagent. Read, append, and update
sheets via the Google Sheets tools. Return small results inline; for
larger results, write a CSV into `/workspace/sessions/<conv>/artifacts/`
and tell the executor where it landed.
""",
        "skills": {
            "read-range": (
                "Read a range from a sheet",
                """# Read a range from a sheet

Inputs: spreadsheet id (or url), sheet name, A1 range (default: whole
sheet). Return rows as a list of dicts when there's a header row;
otherwise as a list of lists.
""",
            ),
            "append-rows": (
                "Append rows to a sheet",
                """# Append rows to a sheet

Inputs: spreadsheet id, sheet name, list of rows (each row a list aligned
to the header). Confirm the header columns before writing if the sheet
isn't fresh.
""",
            ),
        },
    },
    "todoist": {
        "prompt": """# Todoist subagent

You are the Todoist specialist subagent. Manage the user's Todoist
projects, tasks, and labels. Default project is Inbox unless the user
specifies otherwise.
""",
        "skills": {
            "create-task": (
                "Create a task",
                """# Create a Todoist task

Inputs: content (the task itself), optional project, due_string (e.g.
"tomorrow 9am"), priority (1-4), labels.
Confirm the project if the user gave a name that matches more than one.
""",
            ),
            "list-tasks": (
                "List tasks",
                """# List tasks

Inputs: optional project, optional filter (e.g. "today", "overdue"),
optional label. Return: content, due date, priority, project name.
""",
            ),
        },
    },
}


def integration_skills_block(subagent_id: str) -> str:
    """Markdown listing of an integration subagent's available skills.

    Injected into the subagent's dynamic-context system message so the LLM
    sees skill names + descriptions + on-disk paths every turn and can `cat`
    the right `skill.md` before acting. Source: the canonical SKILL.md
    library under ``apps/api/app/agents/skills/builtin/``, loaded by
    ``skill_loader.skills_by_subagent``. Returns "" if there are no skills
    targeting this subagent (custom MCP, brand-new integration, etc.).
    """
    from app.agents.workspace.skill_loader import skills_by_subagent

    skills = skills_by_subagent().get(subagent_id) or []
    if not skills:
        return ""
    base = f"/workspace/integrations/{subagent_id}/agent/skills"
    lines = [f"## Available skills for {subagent_id}"]
    lines.append(
        f"Read `{base}/<slug>/skill.md` before invoking the underlying tool. "
        "The body is the full recipe; the description below is a one-line "
        "trigger so you know which file to cat."
    )
    for skill in skills:
        desc = (skill.description or "").strip()
        suffix = f" — {desc}" if desc else ""
        lines.append(f"- **{skill.name}** (`{base}/{skill.slug}/skill.md`){suffix}")
    return "\n".join(lines)


__all__ = [
    "INDEX_MD",
    "INTEGRATIONS_GUIDE_MD",
    "SESSIONS_GUIDE_MD",
    "integration_skills_block",
]
