# Screenshots and the PR

## Capture protocol

Screenshots come from the running app driven with agent-browser
(driving-gaia §6), authenticated as the seeded dev user. Never mock a state
the code cannot reach.

- **BEFORE** (pipeline phase 3): clean base-branch code running; capture
  every surface the feature will change, at the routes/states you will
  re-capture after. For a brand-new surface, "before" is whatever exists
  today — the page it will be added to, or a 404. That is honest and fine.
- **AFTER** (phase 7): same shot-list, same viewport — plus the states that
  show the feature working: filled, empty, error. Desktop-width always; add
  mobile-width shots for UI-heavy features.
- Under `--sim`, scripted directives (driving-gaia §3) reproduce identical
  chat states in both passes — use them for deterministic before/after pairs.
- Name pairs so they sort together: `todo-panel-before.png`,
  `todo-panel-after.png`, `todo-panel-empty-after.png`. Keep files in the
  scratchpad, never in the repo tree.

## Publishing

The repo is public, so SHA-pinned raw URLs render in PR bodies. Screenshots
travel on a dedicated branch so they never touch the PR diff:

1. Create branch `screenshots/<feature-branch-name>` from `develop` (GitHub
   MCP `create_branch`). Nothing triggers CI on `screenshots/*`.
2. Upload each PNG with `create_or_update_file` (base64 content) under
   `<feature-branch-name>/`.
3. Embed via the **commit SHA** from the upload response — immutable, and
   unambiguous even with slashes in the branch name:
   `https://raw.githubusercontent.com/theexperiencecompany/gaia/<sha>/<path>.png`
4. Leave the branch in place after merge — the SHA-pinned URLs stay valid
   only while the commit is reachable.

## The PR

Title: `<type>(<optional scope>): <description>` — a CI check validates the
type against the allowed list in `pr-naming-conventions.yml` (read the list
there; it drifts). Base: `develop`. If a repo PR template exists, fill it in
— but the `## Before / After`, `## Verification`, and `## Not verified`
sections below are mandatory evidence and always appear, template or not.
With no template, use this body structure:

```markdown
## What & why
<the feature, the user problem, key decisions and any scope choices made>

## How it works
<data flow end to end, files/layers touched>

## Before / After
| Surface | Before | After |
|---|---|---|
| <name> | <img src="...before.png" width="420"> | <img src="...after.png" width="420"> |

## Verification
- <each acceptance criterion, with how it was verified against the running app>
- Journey driven end to end via agent-browser as the dev user: <summary>
- Console and network clean on all driven pages: <yes / details>
- Local gates green: lint / type-check / build / tests / code-quality lanes
- <run mode used: --sim or --agent, and why>

## Not verified
<anything you could not exercise, stated plainly; "nothing" if nothing>
```

After opening the PR, subscribe to its activity and enter the drive-to-green
loop (ci-and-review.md).
