# effect-ui-migration

Outcome: One draft PR ports GAIA routes to Effect UI with 1:1 visual parity and a repeatable visual + Playwright + Story/Scene gate; the first slice is `/todos`.
Status: in-progress
Branch: feat/effect-ui-migration
Worktree: /Users/aryan/Projects/worktrees.noindex/gaia/feat-effect-ui-migration
Ports: web=3740 api=8740
PR: https://github.com/theexperiencecompany/gaia/pull/2002

Proof: .context/proofs/effect-ui-visual/todos-{react,effect,diff}.png (0.000%, 0/277,816 px)
Proof: apps/web/e2e/effect-ui/todos.spec.ts passes against `/todos?effect=1`

## Done and proven
- Effect UI package + Next bridge (`EffectRoot`) — typecheck + runtime verified in browser.
- Todos list ported 1:1 (classes/DOM from TodoItem/TodoList) — 0.000% pixel diff.
- Todo toggle + persistence E2E + axe — passed.
- Unit tests for query/toggle story + scene — passed.
- Draft PR #2002 pushed.

## Doing
- Parallel ports: pins, notifications, settings/account.
- E2E route manifest, score harness, CI workflow.
- Independent review of the slice.

## Next
- Add visual-parity entries for each ported route.
- Run the all-route smoke suite and store proof.
- Cut over each route after its gates pass; delete the React branch.

## Blocked
- Effect UI is public preview / not npm; snapshot pinned at 82a1750.
- `@effect/ui` SSR is Vite-only; Next bridge is client-only.

## Parked
- Chat/OpenUI, Recharts, i18n (next-intl) — need rebuilds, not renames.
- Migrating the Next shell itself.
