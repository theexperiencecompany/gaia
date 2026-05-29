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

from app.agents.workspace.skill_loader import skills_by_subagent

INDEX_MD = """# /workspace — your operating environment

This is your persistent root inside the sandbox. Everything you create
here survives across conversations for this user.

## Top-level layout

    sessions/         per-conversation working trees (see sessions/GUIDE.md)
    integrations/     connected integrations: subagents, prompts, skills
                      (present only when the user has connected one)
    skills/           reusable agent skills (when present)
    todos/            the USER's own todo list (the things in their UI).
                      One folder per active user todo. (see todos/GUIDE.md)
    gaia-tasks/       YOUR (the agent's) work threads — institutional memory
                      of initiatives you've worked on. (see gaia-tasks/GUIDE.md)
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
3. **Use bash.** You have a full Linux shell with python, node, pip, and
   npm. Install whatever you need on the fly — `pip install` and `npm install`
   persist across conversations (the workspace is on durable storage).
   System-level commands that require root are NOT available; the sandbox
   user has no `sudo`. If something needs a package that isn't already in
   the image, install it under your own user (`pip install --user`).
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
                instructions.md     the USER's custom instructions for this
                                    integration (e.g. "focus on #eng, #design").
                                    May be absent if the user hasn't set any.
                skills/<slug>/
                    skill.md        a single named capability — when to use
                                    it and how. Read these on demand; the
                                    subagent's runtime context already lists
                                    them by title and path.

## Rules

1. **These files are read-only on disk.** They are materialized by the runtime
   from MongoDB. A direct `Write` / `Edit` / `sed -i` either fails or is
   silently clobbered on the next sync — never edit them in place.
2. **`instructions.md` is editable, but only through its tool.** It is a
   projection of the user's saved custom instructions. To change it, call
   `update_integration_instructions(integration_id, content)` — that updates
   the source of truth and the projection re-syncs. The matching subagent also
   receives this content directly in its context, so it acts on the guidance
   without having to `cat` the file. Persist only durable preferences (focus
   areas, defaults, conventions) — never one-off, task-specific corrections.
3. **Skills are addressable docs, not code.** Each `skill.md` is a
   self-contained recipe. The subagent decides which one applies and `cat`s
   it before acting.
4. **One integration per subagent.** The gmail subagent uses
   `integrations/gmail/agent/`; the googlecalendar subagent uses
   `integrations/googlecalendar/agent/`. They never cross-read.
"""


GAIA_TASKS_GUIDE_MD = """# Gaia-tasks — your institutional memory of work threads

Each active gaia-task (one "initiative" you've worked on) has a folder
here:

    gaia-tasks/
        GUIDE.md                              (this file)
        index.md                              one-line summary, freshest first
        <slug>-<shortid>/
            canvas.md                         the agent-written brain dump
            log.md                            system-written audit trail
            meta.json                         labels, due, priority, schedule, refs

The folder name is `<slug>-<shortid>`. `<slug>` is a kebab-case form of
the title (e.g. `rahul-contract-q4`); `<shortid>` is the first 8 hex
chars of the Mongo ObjectId for disambiguation. You can `ls` and pick a
task by its readable slug without opening any file.

"Active" = the doc has the ``gaia-tracked`` label AND is either still
open OR completed within the last 30 days. Older completed gaia-tasks
drop out of `ls` here; ``search_todo_context`` still finds them via
embeddings.

## How to read

- `ls gaia-tasks/` — scan everything currently in memory.
- `cat gaia-tasks/index.md` — one-line summary for each, freshest first.
- `cat gaia-tasks/<slug>-<shortid>/canvas.md` — full state of one task.
  Fastest read path when you already know the folder.
- `cat gaia-tasks/<slug>-<shortid>/meta.json` — labels, due, schedule, refs.
- `grep -r "rahul" gaia-tasks/` — find any task mentioning a name or id
  without firing a semantic search.

## How to mutate

These files are **read-only projections** of MongoDB state. Editing them
with `Write` / `Edit` / `sed -i` will fail with `Permission denied` —
that is intentional. Mutations flow through the existing gaia-task tools,
which update Mongo and trigger a sync back to this directory:

- `create_tracked_todo` — creates a new folder here.
- `update_tracked_todo_canvas` — rewrites `canvas.md`.
- `update_tracked_todo` — rewrites `meta.json`.
- `complete_tracked_todo` — folder stays for up to 30 days, then drops.
- `archive_tracked_todo` — same as completing with a system-generated
  summary; folder drops on the same 30-day window.

`log.md` is system-written; you do not need to touch it.

## When to prefer this over tools

- Already know the folder (e.g. it was in a previous message, a
  notification, or `index.md`): `cat gaia-tasks/<slug>-<shortid>/canvas.md`
  beats `search_todo_context`.
- Scanning for context at the start of a session: `cat gaia-tasks/index.md`
  beats `list_tracked_todos`.
- Free-text find for a person, project, or external id: `grep -r`.

## What does NOT live here

- The user's own todo list lives at `/workspace/todos/` — that is the
  inbox the user sees in the UI. Do not confuse it with `gaia-tasks/`.
- General semantic memory (facts about the user, summaries, preferences)
  lives elsewhere — use the `add_memory` / `search_memory` tools.
"""


USER_TODOS_GUIDE_MD = """# Todos — the USER's own todo list

Each active todo from the user's own todo list (the one they see in
the UI) has a folder here:

    todos/
        GUIDE.md                              (this file)
        index.md                              one-line summary, freshest first
        <slug>-<shortid>/
            meta.json                         title, due, priority, labels,
                                              project, subtasks, completion

The folder name is `<slug>-<shortid>` — kebab-case title plus first 8
hex chars of the Mongo ObjectId. `ls todos/` shows the user's plate at
a glance.

"Active" = the todo is NOT a ``gaia-tracked`` doc AND is either still
open OR completed within the last 7 days. Older completed todos drop
out of `ls` here.

## How to read

- `ls todos/` — what's on the user's plate right now.
- `cat todos/index.md` — one-line summary per todo, freshest first.
- `cat todos/<slug>-<shortid>/meta.json` — title, due, priority, labels,
  project_id, subtasks (with their completion status).

## How to mutate

These files are **read-only projections** of MongoDB state. Editing
them with `Write` / `Edit` / `sed -i` will fail with `Permission denied`.

The user normally mutates their todos via the UI. You can mutate them
through the tracked-todo / todo tools when explicitly asked (e.g.
"mark my dentist todo done"); the projection re-syncs after the tool
call commits.

## What does NOT live here

- Your own work threads (institutional memory) live at
  `/workspace/gaia-tasks/`. Those have `canvas.md` + `log.md` and are
  for tracking initiatives across conversations.
- This is just the user's UI todo list — no canvas, no log.
"""


def integration_skills_block(subagent_id: str) -> str:
    """Markdown listing of a subagent's available skills, or "" if none."""
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
    "GAIA_TASKS_GUIDE_MD",
    "INDEX_MD",
    "INTEGRATIONS_GUIDE_MD",
    "SESSIONS_GUIDE_MD",
    "USER_TODOS_GUIDE_MD",
    "integration_skills_block",
]
