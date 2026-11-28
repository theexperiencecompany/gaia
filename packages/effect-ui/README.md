# @heygaia/effect-ui

Effect UI migration surface for GAIA web. The React app stays the host during
the migration; each route is either React or Effect UI, never both in one tree.

## Architecture

- `src/domain/` — `Schema` types for API payloads.
- `src/services/` — Effect services. `Api` is the only HTTP surface; the host
  supplies the base URL.
- `src/pages/<feature>/` — one component per route, with its queries and
  commands in the same file.
- `apps/web/src/components/effect/EffectRoot.tsx` — mounts one root per Next
  route. It owns the `Api` layer and interrupts the root on unmount.
- `apps/web/src/components/effect/pages/Effect<Route>Page.tsx` — client
  adapter. A Server Component cannot pass a function to a Client Component.
- The real route gets `?effect=1` and branches to the adapter. This keeps the
  Next shell, i18n, auth, and URL identical while the port is verified.

## Porting a route

1. Open the React route and its components. Copy the exact DOM structure and
   Tailwind classes; do not invent a new design.
2. Add `src/pages/<feature>/<Feature>Page.ts` with the `Query.Service` and
   `Command.Service` definitions beside the component.
3. Add `apps/web/src/components/effect/pages/Effect<Feature>Page.tsx`.
4. Add the `effect === "1"` branch to the real page. Keep the old branch.
5. Add `test/<Feature>Page.test.ts` with a Story and a Scene test.
6. Add the route to `apps/web/scripts/effect-ui/visual-parity.mjs` and prove
   the pixel diff against the React route.
7. Add a Playwright spec under `apps/web/e2e/effect-ui/`. Do not run it while
   another agent is using the shared dev DB.
8. Delete the React branch only after the visual diff, axe, and E2E pass.

## Commands

```bash
mise exec -- pnpm --filter @heygaia/effect-ui typecheck
mise exec -- pnpm --filter @heygaia/effect-ui test
mise exec -- pnpm --filter gaia type-check

# from apps/web, against a running stack
WEB_PORT=3740 API_PORT=8740 node scripts/effect-ui/visual-parity.mjs
WEB_PORT=3740 API_PORT=8740 pnpm exec playwright test e2e/effect-ui
```

## Non-negotiables

- No React, HeroUI, Radix, or `next/*` imports in `src/**`.
- One Effect UI root per route. Multiple roots duplicate the query cache.
- Server data lives in `queries`; the Model holds user intent only.
- Commands and Subscriptions, not `useEffect`.
- Copy GAIA's classes and DOM. A new design is a failed migration.
- Pin the snapshot SHA (`82a1750`); do not track `main`.
