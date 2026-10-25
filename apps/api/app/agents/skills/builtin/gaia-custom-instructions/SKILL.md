---
name: gaia-custom-instructions
description: How the user's standing instructions work (for every conversation or one integration), how to read and update them, how they rank against platform rules, and when a preference belongs here rather than in a skill, a tracked todo or memory. Read this when a user states how GAIA or a specific integration should behave from now on.
target: executor
---

# Standing Instructions

The user can give GAIA standing instructions: lasting preferences for how it
should behave. Each set has a scope:

- `global`: applies to every conversation ("always reply in Spanish",
  "keep answers under five lines").
- an integration id (`slack`, `linear`, `gmail`, ...): applies to that
  integration's work only ("for Slack, focus on #eng and #design").

## Where they live

- **Source of truth:** the user's account, one record per scope. The user edits
  them in Settings, and the integration page shows the integration scopes.
- **In context automatically:** the global scope reaches every turn, and an
  integration scope reaches that integration's work, each as a
  `<user_instructions scope="...">` block. You rarely need to read them.
- **Mirrored read-only** to `account/custom-instructions.json` (global) and
  `integrations/<id>/agent/instructions.md` (per integration). Never edit those
  files: they are projections and the edit will not stick.

## How they rank

They are preferences, not rules. They shape tone, format, defaults and focus.
They never override the platform rules in the system prompt on safety, privacy,
approvals or how tools and data are handled. If one asks for something those
rules forbid ("never ask me before sending"), follow the rules and tell the user
plainly what you could not do. Approval gates are enforced by GAIA itself, so
instruction text cannot switch them off anyway.

Between user-level sources the more specific wins: the user's current message,
then the active task's notes, then the skill for the task, then their standing
instructions.

## Reading and updating

- `get_user_instructions(scope)` returns the current text and its revision.
  Call it right before every save.
- `update_user_instructions(scope, content, based_on_revision)` saves the FULL
  new text. It replaces rather than appends, so read, merge, then write the
  whole thing back with the revision you read. A save built on an older
  revision is refused so it never drops a newer edit; read again and merge.
  An empty string clears the scope. An integration scope must be one the user
  has connected. The user always confirms the exact text on an approval card
  before it saves, so keep it short and in their words. If they decline, nothing
  is saved; do not ask again in the same turn.

## Instructions, skill, tracked todo or memory?

- **Standing instruction:** how GAIA should behave for this user from now on.
- **Skill:** a reusable procedure for a kind of task (`save_learned_skill`,
  `update_skill`).
- **Tracked todo:** ongoing work and its state (dates, progress, people
  waiting).
- **Memory:** facts about the user. It is captured automatically.

Persist only DURABLE preferences. Do not save one-off requests ("send this one
to #random") or corrections that only apply to the current task. If you are
unsure whether a preference is meant to last, ask once before saving.

## Typical flow

1. User: "From now on, for Slack, focus on #eng, #design, and #pm."
2. Recognise a durable preference for the `slack` scope.
3. Call `update_user_instructions(scope="slack", content="<full instructions
   including the focus channels>")`.
4. Confirm briefly. Every future Slack task sees it, and the user can review or
   edit it in Settings.
