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

Upload to the shared `pr-assets` branch and embed by raw URL — the mechanics,
including the render-failure diagnosis, live in the **`pr-image-embedding`
skill**. Do not invent a per-PR assets branch.

## The PR

Title, body, and section-by-section guidance are owned by the
**`writing-pull-requests` skill** and the repo template it fills,
`.github/pull_request_template.md`. Follow it — base `master`, Conventional
Commit title, never merge.

Two of that template's sections are non-negotiable for a ship-feature run,
because this pipeline exists to produce the evidence behind them:

- **Screenshots** — the before/after table from the capture protocol above.
- **How to verify** + **Not verified** — each acceptance criterion with how it
  was exercised against the running app, the run mode used (`--sim` or
  `--agent`) and why, and an honest list of what you could not drive.

After opening the PR, subscribe to its activity and enter the drive-to-green
loop (ci-and-review.md).
