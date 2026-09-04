"""On-disk workspace docs (INDEX.md + per-category GUIDE.md).

These are the projections materialized into each user's workspace so the
filesystem is self-describing for anyone who `ls`/`cat`s it. The *canonical*
prose now lives in ``operational_docs.py`` (the single source of truth the
agent also receives by injection / ``read_manual``); this module is a thin
on-disk view over it, plus ``INDEX_MD`` (the FS map) and the per-subagent
skills listing.

One source of truth: the per-category guide bodies below are re-exported from
``operational_docs`` so the on-disk copy never diverges from what the agent is
told in-context.
"""

from __future__ import annotations

from app.agents.workspace.operational_docs import (
    INTEGRATIONS_DOC,
    MEMORY_DOC,
    SESSIONS_ARTIFACTS_DOC,
    TRACKED_TODOS_DOC,
    USER_TODOS_DOC,
)
from app.agents.workspace.skill_loader import skills_by_subagent

INDEX_MD = """# /workspace: your operating environment

This is your persistent root inside the sandbox. Everything you create
here survives across conversations for this user.

## Top-level layout

    sessions/         per-conversation working trees (see sessions/GUIDE.md)
    integrations/     connected integrations: subagents, prompts, skills
                      (present only when the user has connected one)
    skills/           reusable agent skills (when present)
    todos/            the USER's own todo list (the things in their UI).
                      One folder per active user todo. (see todos/GUIDE.md)
    gaia-tasks/       YOUR (the agent's) work threads: institutional memory
                      of initiatives you've worked on. (see gaia-tasks/GUIDE.md)
    memory/           your long-term memory about the user: core documents,
                      daily journal, facts by topic. Read-only projection;
                      mutate via the memory tools. (see memory/GUIDE.md)
    account/          the USER's account: subscription, usage, settings.
                      Read-only projection — mutate via the account tools.
                      (see account/GUIDE.md)
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

# Per-category guides are the canonical operational docs, re-exported here so
# the on-disk GUIDE.md projection stays a single-source view (no duplication).
SESSIONS_GUIDE_MD = SESSIONS_ARTIFACTS_DOC
INTEGRATIONS_GUIDE_MD = INTEGRATIONS_DOC
GAIA_TASKS_GUIDE_MD = TRACKED_TODOS_DOC
USER_TODOS_GUIDE_MD = USER_TODOS_DOC
MEMORY_GUIDE_MD = MEMORY_DOC

ACCOUNT_GUIDE_MD = """# account/ — the user's account state

Everything here is a READ-ONLY projection of the user's real account data.
The JSON files are views for you to read; editing one accomplishes nothing.
To change anything, use the mutation tools listed per topic below — every one
of them asks the user for confirmation before it runs, no matter their
approval settings.

Read `account/guides/<topic>.md` before acting on that topic:

    subscription.json          plan, status, renewal        → guides/subscription.md
    usage.json                 allowance % used, resets     → guides/usage.md
    notifications.json         channel on/off flags         → guides/notifications.md
    preferences.json           response style, timezone     → guides/preferences.md
    custom-instructions.json   standing instructions        → guides/custom-instructions.md
    voices/                    catalog + selection          → guides/voices.md
    linked-accounts/           platform link status         → guides/linked-accounts.md

Files may be up to a minute stale behind the database; when exactness matters,
say so rather than presenting a read as live truth.
"""

ACCOUNT_SUBSCRIPTION_GUIDE_MD = """# subscription

`account/subscription.json` mirrors the billing provider's record: current
plan, price and cycle, next renewal date, whether a cancellation is scheduled,
and recent charges.

READ-ONLY — you cannot modify or cancel a subscription. If asked, say so
plainly; cancellations and plan changes happen through the billing page in the
GAIA settings UI. There is no tool for it and there never will be by your hand.
"""

ACCOUNT_USAGE_GUIDE_MD = """# usage

`account/usage.json` shows how much of the user's daily (and monthly, on Pro)
allowance has been consumed, as percentages with reset times, plus recent
activity counts. Raw spend is deliberately never shown.

READ-ONLY — usage is recorded automatically; nothing to change.
"""

ACCOUNT_NOTIFICATIONS_GUIDE_MD = """# notifications

`account/notifications.json` lists each notification channel (email, telegram,
discord, whatsapp, slack) with its enabled flag.

TO CHANGE: `update_notification_settings(channel=on/off, ...)`. It pauses for
the user's approval first — even when they normally auto-approve actions.
"""

ACCOUNT_PREFERENCES_GUIDE_MD = """# preferences

`account/preferences.json` carries the response style (brief / detailed /
casual / professional or a custom label) and home timezone (IANA name).

TO CHANGE: `update_preferences(response_style=..., timezone=...)`. It asks the
user to confirm before applying. Timezone must be an IANA identifier such as
'Asia/Kolkata' or 'America/New_York'.
"""

ACCOUNT_CUSTOM_INSTRUCTIONS_GUIDE_MD = """# custom-instructions

`account/custom-instructions.json` holds standing instructions the user wants
applied to every conversation (max 500 chars).

TO CHANGE: `update_custom_instructions(instructions=...)`. It pauses for the
user's approval first. Passing an empty string clears the instructions.
"""

ACCOUNT_VOICES_GUIDE_MD = """# voices

`voices/catalog.json` lists available voices (id, name, starred);
`voices/selected.json` names the voice currently used for spoken replies.

TO CHANGE: `set_selected_voice(voice=...)` with a voice name or id from the
catalog. It asks the user to confirm before switching.
"""

ACCOUNT_LINKED_ACCOUNTS_GUIDE_MD = """# linked-accounts

One file per supported platform (`telegram.json`, `whatsapp.json`,
`discord.json`, `slack.json`, `imessage.json`): connected or not, and if
connected, since when and which handle.

TO LINK a new platform: `manage_linked_account(platform, action="generate_link")`
— returns a single-use URL the user opens to finish connecting. This does not
need approval.

TO DISCONNECT: `manage_linked_account(platform, action="disconnect")` — always
asks for confirmation first. Never edit these files; they only report status.
"""


def integration_skills_block(subagent_id: str) -> str:
    """Markdown listing of a subagent's available skills, or "" if none."""
    skills = skills_by_subagent().get(subagent_id) or []
    if not skills:
        return ""
    base = f"/workspace/integrations/{subagent_id}/agent/skills"
    lines = [f"## Available skills for {subagent_id}"]
    lines.append(
        f"Read `{base}/<slug>/skill.md` before invoking the underlying tool. Use "
        "the exact path shown for each skill below; do not rewrite it. The body is "
        "the full recipe; the description below is a one-line trigger so you know "
        "which file to cat."
    )
    for skill in skills:
        desc = (skill.description or "").strip()
        suffix = f": {desc}" if desc else ""
        lines.append(f"- **{skill.name}** (`{base}/{skill.slug}/skill.md`){suffix}")
    return "\n".join(lines)


__all__ = [
    "ACCOUNT_CUSTOM_INSTRUCTIONS_GUIDE_MD",
    "ACCOUNT_GUIDE_MD",
    "ACCOUNT_LINKED_ACCOUNTS_GUIDE_MD",
    "ACCOUNT_NOTIFICATIONS_GUIDE_MD",
    "ACCOUNT_PREFERENCES_GUIDE_MD",
    "ACCOUNT_SUBSCRIPTION_GUIDE_MD",
    "ACCOUNT_USAGE_GUIDE_MD",
    "ACCOUNT_VOICES_GUIDE_MD",
    "GAIA_TASKS_GUIDE_MD",
    "INDEX_MD",
    "INTEGRATIONS_GUIDE_MD",
    "MEMORY_GUIDE_MD",
    "SESSIONS_GUIDE_MD",
    "USER_TODOS_GUIDE_MD",
    "integration_skills_block",
]
