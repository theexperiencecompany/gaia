# effect-ui-migration

Outcome: One draft PR ports GAIA routes to Effect UI with 1:1 visual parity and a repeatable visual + Playwright + Story/Scene gate; four routes are verified.
Status: in-progress
Branch: feat/effect-ui-migration
Worktree: /Users/aryan/Projects/worktrees.noindex/gaia/feat-effect-ui-migration
Ports: web=3740 api=8740
PR: https://github.com/theexperiencecompany/gaia/pull/2002

Proof: .context/proofs/effect-ui-visual/*-{react,effect,diff}.png
- todos 0.000%, notifications 0.000%, settings/account 0.000%, pins 0.107%
Proof: apps/web/e2e/effect-ui — 10/10 passed
Proof: score 4/87 (4.6%), zero React imports under packages/effect-ui/src

## Done and proven
- Effect UI package + Next bridge; lazy route chunks; dev-only `?effect=1` gate.
- Four routes ported 1:1 with exact GAIA classes/DOM.
- Story/Scene tests 19/19; full web typecheck; visual + Playwright + axe gates.
- Route manifest 87 pages / 81 runnable / 6 explicit skips; score + CI gate.

## Doing
- Remaining 83 routes.
- TODO before promoting each route: replace the React branch, delete the flag.

## Next
- Wave 2: todos filters (`today`, `upcoming`, `completed`), then calendar/mail/workflows.
- Port todo description/meta/workflow chips before claiming full Todos parity.
- Host cutover: Vite + `HtmlServerVite`, `Session`/`I18n` services.

## Blocked
- Effect UI is public preview / not npm; snapshot pinned at 82a1750.
- Chat/OpenUI, Recharts, i18n need rebuilds, not renames.
- Settings sign-out is painted but inert; notifications actions/websocket not ported.

## Parked
- Migrating the Next shell itself.
