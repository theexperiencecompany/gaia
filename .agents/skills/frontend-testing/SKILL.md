---
name: frontend-testing
description: How to test GAIA's frontend — three tiers (vitest units, Testing Library components, Playwright e2e), the red-green-throwaway pattern for pre-merge sweeps, and the gotchas that bit us during the 2026 react-doctor sweep.
---

# Frontend Testing in GAIA

Three tiers, matched to risk. Pick the cheapest tier that can actually catch the bug class you're worried about.

## Tier 1 — vitest unit tests (pure logic)

`apps/web/vitest.config.ts` runs with `environment: "node"` — fast, no DOM.

```bash
cd apps/web && pnpm exec vitest run src/__tests__/<name>.test.ts
```

Use for anything pure: key derivation, clamps/selection math, URL parsers, upsert/merge semantics, formatters. Put files in `apps/web/src/__tests__/`. If a function under test is module-private, temporarily add `export`, revert after.

## Tier 2 — component interaction tests (Testing Library)

Not installed by default. Install temporarily:

```bash
pnpm add -D @testing-library/react @testing-library/dom jsdom -w
```

Test file needs `// @vitest-environment jsdom` at the top. Render the leaf component directly with minimal props; assert on behavior (clicks fire the right handler, keyboard fires once), not styling.

Z-order and overlay patterns (stretched-button over a card, `z-10` overlay + raised children) are verifiable here: click the covered child → its handler fires; click the bare area → overlay handler fires; keyboard Enter → same as click.

**Cleanup protocol when tests were a temporary verification sweep:** `git checkout -- apps/web/package.json pnpm-lock.yaml && git clean -fd apps/web/src/__tests__/` — never commit sweep-only deps or files unless promoting them to permanent.

## Tier 3 — Playwright e2e (real app journeys)

Config already exists: `apps/web/playwright.config.ts` + `apps/web/e2e/` (harness mints a dev user; auth bypass is on in dev).

```bash
# terminal 1 — boots API + web natively (scripted LLM stub, no OpenRouter cost)
mise dev --sim

# terminal 2 — run specs against the running stack
cd apps/web && pnpm exec playwright test e2e/<journey>.spec.ts
```

Write one spec per user journey (composer slash-nav, mail row actions, todo open/edit, settings usage charts). Use `WEB_PORT`/`API_PORT` env for per-worktree ports. First route visit pays Turbopack compile — timeouts are already set to 120s, don't lower them.

## Red-green-throwaway pattern (pre-merge verification sweeps)

For big refactor branches where you don't want permanent test files:

1. Write the failing test demonstrating the bug/risk (RED).
2. Fix the code (GREEN).
3. Delete the test file, revert dep installs.
4. Keep only tests that pin contracts worth maintaining forever — those graduate into `src/__tests__/` permanently.

## Gotchas that bit us (2026 sweep)

- **Index-space divergence**: if rendered rows compare an UNLOCKED-list index but a handler indexes the FULL list, locked items interleaved in results make highlight and activation disagree. All selection arithmetic must share one index space (see `clampSelection` in useSlashCommandDropdownState.ts).
- **Content-hash keys remount on growth**: keys derived from entry payloads change every streamed delta → cards unmount/remount mid-stream (state loss, flicker). Derive keys from creation-time identity (ids, timestamps stamped at synthesis), not content. See deriveStableKeys in useSubagentSynthesis.ts.
- **Slice-splice status arrays corrupt on out-of-order writes**: `[...prev.slice(0,i), v, ...prev.slice(i+1)]` APPENDS when `i > prev.length`. Use index assignment on a copy with gap-fill.
- **Biome unsafe fixes**: `--write` skips them; add `--unsafe` or apply by hand. `nx lint web` = biome check without write.
- **react-doctor changed-scope gate**: fails the PR on ANY new warning vs merge-base. Run `npx react-doctor@0.9.12 --json -y --project apps/web --scope changed --base origin/master` locally before pushing.
- **Sonar S6759 readonly-props**: fires on every decomposed component's props interface; accepted noise (gate doesn't fail on it) unless the team opts in.
- **Per-project config layering**: workspace-level checks (supplyChain) read ONLY the root config when invoked with `--project '*'`; per-project configs in apps/web layer for rule settings but not for supplyChain floors.
