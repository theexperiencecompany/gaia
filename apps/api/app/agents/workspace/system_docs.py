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


__all__ = ["INDEX_MD", "SESSIONS_GUIDE_MD"]
