---
name: gaia-custom-instructions
description: How per-integration custom instructions work — reading them, updating them, and when to persist a user's preference (e.g. "for Slack focus on #eng"). Read this when a user states how a specific integration should be used, or asks where their integration instructions live.
target: executor
---

# Per-Integration Custom Instructions

Every connected integration can carry a block of custom instructions — standing
guidance for how the user wants that service used (focus channels, default
projects, conventions). This is the per-integration equivalent of a project's
README: durable, scoped to one integration, honored on every future task.

## Where they live

- **Source of truth:** the user's account (one record per integration).
- **Surfaced to the matching subagent** automatically every turn, as a
  "CUSTOM INSTRUCTIONS FOR <INTEGRATION>" block — the slack subagent always sees
  the slack instructions without reading a file.
- **Mirrored read-only** to `integrations/<id>/agent/instructions.md` in the
  workspace, so it's also greppable. Never edit that file directly — it's a
  projection and the edit won't stick.
- **Editable by the user** on the integrations page in the app.

## Reading them

- `get_integration_instructions(integration_id)` returns the current content.
- A subagent already has its own integration's instructions in context, so it
  rarely needs to call this. The executor should call it before amending.

## Updating them

`update_integration_instructions(integration_id, content)` saves the FULL new
body (it replaces, it does not append). To amend, read first (or use the block
already in context), merge, then write the whole thing back.

## When to persist (and when NOT to)

Persist only DURABLE preferences — things that should apply to every future task
on that integration:

- "Always post to #eng and #design, never #general."
- "Default Linear issues to the Backend project."
- "When emailing clients, cc my assistant."

Do NOT persist one-off, task-specific instructions:

- "Send this particular message to #random." (just do it this turn)
- A correction that only applies to the current request.

If you're unsure whether a preference is durable, it's fine to ask the user
whether they want it remembered for next time before writing it.

## Typical flow

1. User: "From now on, for Slack, focus on #eng, #design, and #pm."
2. You recognize a durable preference for the `slack` integration.
3. Call `update_integration_instructions("slack", "<full instructions including
   the focus channels>")`.
4. Confirm briefly. From then on the slack subagent sees this guidance every
   turn, and the user can review/edit it on the integrations page.
