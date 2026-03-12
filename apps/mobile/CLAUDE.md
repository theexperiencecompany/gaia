# CLAUDE.md — apps/mobile

React Native (Expo) mobile app for GAIA.

## Key Commands

```bash
nx dev mobile          # Start Expo dev server
nx lint mobile
nx type-check mobile
```

## DRY — Shared Logic

**Mobile code must not duplicate logic that already exists (or should exist) in shared libs.**

- Before writing a utility, hook, API client, or type in `apps/mobile/`, **search `libs/shared/ts/src/` first**.
- If logic is already implemented in `apps/web` or `apps/desktop` and is platform-agnostic, **move it to `libs/shared/`** rather than copying it into mobile.
- Platform-specific rendering (React Native components, navigation) stays in `apps/mobile/`. Business logic, data transformations, API calls, and type definitions belong in shared.
- When adding new shared logic, update the `libs/shared/ts/src/index.ts` re-exports so all consumers can access it.

**The rule:** if two apps need the same logic, it lives in `libs/shared/` — not in both apps.

## Code Style

- **No inline imports** — all imports at the top of the file
- **Never use `any`** — always provide proper type definitions
- **Before creating a new type, search `libs/shared/ts/src/` and `src/types/` first**
- Expo SDK conventions apply — do not use web-only APIs

## Common Issues

- Metro bundler cache issues → `nx dev mobile --reset-cache`
- Type errors from shared lib → ensure `libs/shared` is built or referenced via path alias
