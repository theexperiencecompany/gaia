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
    todos/            tracked todos — your institutional memory
                      (see todos/GUIDE.md). One folder per active todo.
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


TODOS_GUIDE_MD = """# Todos — your tracked-todo institutional memory

Each active tracked todo for this user has a folder here:

    todos/
        GUIDE.md           (this file)
        index.md           one-line-per-todo summary, sorted by last update
        <todo_id>/
            canvas.md      the agent-written brain dump for this initiative
            log.md         system-written audit trail (who/what/when)
            meta.json      status, priority, due date, labels, references

"Active" = the todo is labelled ``gaia-tracked`` AND it is either still
open or completed within the last 30 days. Older completed todos drop
out of `ls` here; `search_todo_context` still finds them via embeddings.

## How to read

- `ls todos/` — scan everything currently in memory.
- `cat todos/index.md` — one-line summary for each, freshest first.
- `cat todos/<id>/canvas.md` — full state of one todo. Fastest read path
  when you already know the id (no tool call needed).
- `cat todos/<id>/meta.json` — labels, due date, schedule, references.
- `grep -r "rahul" todos/` — find every todo that mentions a name or id
  without firing a semantic search.

## How to mutate

These files are **read-only projections** of MongoDB state. Editing them
with `Write` / `Edit` / `sed -i` will fail with `Permission denied` —
that is intentional. Mutations flow through the existing tracked-todo
tools, which update Mongo and trigger a sync back to this directory:

- `create_tracked_todo` — creates a new folder here.
- `update_tracked_todo_canvas` — rewrites `canvas.md`.
- `update_tracked_todo` — rewrites `meta.json` (and bumps `updated_at`).
- `complete_tracked_todo` — folder stays for up to 30 days, then drops.
- `archive_tracked_todo` — same as completing with a system-generated
  summary; folder drops on the same 30-day window.

`log.md` is system-written; you do not need to touch it. The
``search_todo_context`` tool still indexes canvas content for fuzzy
recall across all (active + historical) tracked todos.

## When to prefer this over tools

- Already know the id (e.g. it was in a previous message, a
  notification, or `index.md`): `cat todos/<id>/canvas.md` beats
  `search_todo_context`.
- Scanning for context at the start of a session: `cat todos/index.md`
  beats `list_tracked_todos`.
- Free-text find for a person, project, or external id: `grep -r`.
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
    "INDEX_MD",
    "INTEGRATIONS_GUIDE_MD",
    "SESSIONS_GUIDE_MD",
    "TODOS_GUIDE_MD",
    "integration_skills_block",
]
