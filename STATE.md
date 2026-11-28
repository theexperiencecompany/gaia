# effect-ui-migration

Outcome: One draft PR ports GAIA routes to Effect UI with 1:1 visual parity and a repeatable visual + Playwright + Story/Scene gate; the first slice is `/todos`.
Status: in-progress
Branch: feat/effect-ui-migration
Worktree: /Users/aryan/Projects/worktrees.noindex/gaia/feat-effect-ui-migration
Ports: web=3740 api=8740

Proof: .context/proofs/effect-ui-visual/todos-{react,effect,diff}.png (0.139%, row order only)
Proof: apps/web/e2e/effect-ui/todos.spec.ts passes against `/todos?effect=1`

## Done and proven
- Effect UI package + Next bridge (`EffectRoot`) — typecheck + runtime verified in browser.
- Todos list ported 1:1 (classes/DOM from TodoItem/TodoList) — 0.139% pixel diff.
- Todo toggle + persistence E2E + axe — passed.
- Unit tests for query/toggle story + scene — passed.

## Doing
- Parallel ports: pins, notifications, settings/account.
- E2E route manifest, score harness, CI workflow.
- Independent review of the slice.

## Next
- Add visual-parity entries for each ported route.
- Fix remaining row-order diff in the visual fixture (API order is nondeterministic).
- Run the full route smoke suite and store proof.

## Blocked
- Effect UI is public preview / not npm; snapshot pinned at 82a1750.
- `@effect/ui` SSR is Vite-only; Next bridge is client-only.

## Parked
- Chat/OpenUI, Recharts, i18n (next-intl) — need rebuilds, not renames.
- Migrating the Next shell itself.
